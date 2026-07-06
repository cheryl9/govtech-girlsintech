from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import psycopg2
import httpx
import os
import time

app = FastAPI(title="Trade Service")
security = HTTPBearer(auto_error=False)
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth:8001")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory:8002")

# DB Connection
def get_db(): 
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME", "tradedb"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )

def init_db():
    conn = get_db()
    cur = conn.cursor()
    ur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL,
            seller TEXT NOT NULL,
            buyer TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price_per_unit NUMERIC(10, 2) NOT NULL,
            total_price NUMERIC(10, 2) NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

# Startup 
@app.on_event("startup")
def startup():
    for attempt in range(10):
        try:
            init_db()
            print("Database initialized successfully.")
            return
        except Exception as e:
            print(f"DB not ready yet (attempt {attempt + 1}/10): {e}")
            time.sleep(2)
    raise RuntimeError("Could not connect to DB after 10 attempts")

# Models
class TradeRequest(BaseModel):
    item_id: int
    quantity: int

# Auth helper
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str: 
    if not credentials: 
        raise HTTPException(status_code=401, detail = "No token provided")
    try:
        response = httpx.get(
            f"{AUTH_SERVICE_URL}/validate",
            headers={"Authorization": f"Bearer {credentials.credentials}"},
            timeout=5.0
        )
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail = "Invalid token")
        return response.json()["username"]
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail = "Auth service unavailable")

# Routes
@app.get("/health")
def health():
    return {"status": "ok", "service": "trade"}

@app.post("/trade")
def create_trade(
    trade_req: TradeRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    buyer: str = Depends(get_current_user)
):
    """
    Buy an item from inventory.
    The buyer cals this, the item must exist in inventory and belong to someone else. 
    """
    try:
        item_resp = httpx.get(
            f"{INVENTORY_SERVICE_URL}/items/{trade_req.item_id}",
            headers={"Authorization": f"Bearer {credentials.credentials}"},
            timeout=5.0
        )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Inventory service unavailable")
    
    if item_resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Item not found in inventory")
    if item_resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Unexpected inventory service error")
    
    item = item_resp.json()
    seller = item["owner"]

    if seller == buyer:
        raise HTTPException(status_code=400, detail="Cannot trade with yourself")
    
    if item["quantity"] < trade_req.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock. Available: {item['quantity']}"
        )

    total = round(item["price"] * trade_req.quantity, 2)

    # Record transaction in database
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO trades (item_id, seller, buyer, quantity, price_per_unit, total_price, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'completed') RETURNING id""",
            (trade_req.item_id, seller, buyer, trade_req.quantity, item["price"], total)
        )
        trade_id = cur.fetchone()[0]
        conn.commit()
        return {
            "trade_id": trade_id,
            "item_id": trade_req.item_id,
            "seller": seller,
            "buyer": buyer,
            "quantity": trade_req.quantity,
            "price_per_unit": item["price"],
            "total_price": total,
            "status": "completed"
        }
    finally:
        cur.close()
        conn.close()

@app.get("/trades")
def list_my_trades(username: str = Depends(get_current_user)):
    """List all trades where the user is buyer or seller"""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT id, item_id, seller, buyer, quantity, price_per_unit, total_price, status, created_at
               FROM trades WHERE seller = %s OR buyer = %s
               ORDER BY created_at DESC""",
            (username, username)
        )
        rows = cur.fetchall()
        return [
            {
                "id": r[0], "item_id": r[1], "seller": r[2], "buyer": r[3],
                "quantity": r[4], "price_per_unit": float(r[5]),
                "total_price": float(r[6]), "status": r[7], "created_at": str(r[8])
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()

@app.get("/trades/{trade_id}")
def get_trade(trade_id: int, username: str = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT id, item_id, seller, buyer, quantity, price_per_unit, total_price, status, created_at
               FROM trades WHERE id = %s AND (seller = %s OR buyer = %s)""",
            (trade_id, username, username)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Trade not found")
        return {
            "id": row[0], "item_id": row[1], "seller": row[2], "buyer": row[3],
            "quantity": row[4], "price_per_unit": float(row[5]),
            "total_price": float(row[6]), "status": row[7], "created_at": str(row[8])
        }
    finally: 
        cur.close()
        conn.close()