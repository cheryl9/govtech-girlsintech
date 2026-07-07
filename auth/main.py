from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import os
import psycopg2
import time
import hashlib
import secrets

app = FastAPI(title="Auth Service")
security = HTTPBearer(auto_error=False)

REQUEST_COUNT = Counter(
    "auth_requests_total",
    "Total requests to auth service",
    ["method", "endpoint", "status_code"]
)

REQUEST_LATENCY = Histogram(
    "auth_request_duration_seconds",
    "Request duration for auth service",
    ["endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)

LOGIN_ATTEMPTS = Counter(
    "auth_login_attempts_total",
    "Total login attempts",
    ["status"]
)

ACTIVE_SESSIONS = Gauge(
    "auth_active_sessions",
    "Number of users currently logged in"
)

@app.middleware("http")
async def track_metrics(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    endpoint = request.url.path
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        status_code=response.status_code
    ).inc()
    REQUEST_LATENCY.labels(endpoint=endpoint).observe(duration)
    return response

@app.get("/metrics")
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME", "authdb"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            token TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

@app.on_event("startup")
def startup():
    for attempt in range(10):
        try:
            init_db()
            print("Auth DB initialized.")
            return
        except Exception as e:
            print(f"DB not ready yet (attempt {attempt + 1}/10): {e}")
            time.sleep(2)
    raise RuntimeError("Could not connect to DB after 10 attempts")

class UserCredentials(BaseModel):
    username: str
    password: str

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token() -> str:
    return secrets.token_hex(32)

@app.get("/health")
def health():
    return {"status": "ok", "service": "auth"}

@app.post("/register", status_code=201)
def register(creds: UserCredentials):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (creds.username, hash_password(creds.password))
        )
        conn.commit()
        return {"message": f"User '{creds.username}' registered successfully"}
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Username already exists")
    finally:
        cur.close()
        conn.close()

@app.post("/login")
def login(creds: UserCredentials):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id FROM users WHERE username = %s AND password_hash = %s",
            (creds.username, hash_password(creds.password))
        )
        user = cur.fetchone()
        if not user:
            LOGIN_ATTEMPTS.labels(status="failure").inc()
            raise HTTPException(status_code=401, detail="Invalid username or password")
        token = generate_token()
        cur.execute("UPDATE users SET token = %s WHERE id = %s", (token, user[0]))
        conn.commit()
        LOGIN_ATTEMPTS.labels(status="success").inc()
        ACTIVE_SESSIONS.inc()
        return {"token": token}
    finally:
        cur.close()
        conn.close()

@app.get("/validate")
def validate(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="No token provided")
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT username FROM users WHERE token = %s",
            (credentials.credentials,)
        )
        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return {"valid": True, "username": user[0]}
    finally:
        cur.close()
        conn.close()

@app.post("/logout")
def logout(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="No token provided")
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE users SET token = NULL WHERE token = %s",
            (credentials.credentials,)
        )
        conn.commit()
        ACTIVE_SESSIONS.dec()
        return {"message": "Logged out successfully"}
    finally:
        cur.close()
        conn.close()