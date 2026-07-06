from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel 
import os
import psycopg2
import time
import hashlib
import secrets

app = FastAPI(title="Auth Service")
security = HTTPBearer(auto_error=False)

# DB Connection
def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME", "auth_db"),
        user=os.getenv("DB_USER", "auth_user"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )

def init_db():
    conn=get_db()
    cur=conn.cursor()
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

# Startup
@app.on_event("startup")
def startup():
    # retry db connection on startup if DB is not ready yet
    for attempt in range(10):
        try:
            init_db()
            print("Auth DB initialized.")
            return
        except Exception as e:
            print(f"Database connection failed (attempt {attempt + 1}/10): {e}")
            time.sleep(2)
    raise RuntimeError("Could not connect to DB after 10 attempts.")

# Models
class UserCredentials(BaseModel):
    username: str
    password: str

# Helpers
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token() -> str:
    return secrets.token_hex(32)

# Routes 
@app.get("/health")
def health():
    return {"status": "ok", "service": "auth"}

@app.post("/register", status_code=201)
def register(creds: UserCredentials):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", 
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
        cur.execute("SELECT id, password_hash FROM users WHERE username = %s AND password_hash = %s", 
                    (creds.username, hash_password(creds.password))
        )
        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        token = generate_token()
        cur.execute("UPDATE users SET token = %s WHERE id = %s", (token, user[0]))
        conn.commit()
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
        return {"message": "Logged out successfully"}
    finally: 
        cur.close()
        conn.close()