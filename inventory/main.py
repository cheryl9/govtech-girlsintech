from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import psycopg2
import httpx
import os
import time

app = FastAPI(title = "Inventory Service")
security = HTTPBearer(auto_error=False)

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth:8001")

# DB Connection
def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME", "inventory_db"),
        user=os.getenv("DB_USER", "inventory_user"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            price NUMERIC(10,2) NOT NULL DEFAULT 0.00,
            owner TEXT NOT NULL,
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
            print("Inventory DB initialised")
            return
        except Exception as e:
            print(f"DB not ready yet (attempt {attempt + 1}/10): {e}")
            time.sleep(2)
    raise RuntimeError("Could not connect to DB after 10 attempts")

# Models
class Item(BaseModel):
    name: str
    quantity: int
    price: float

class ItemUpdate(BaseModel):
    quantity: int | None = None
    price: float | None = None


# Auth helper
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Call the Auth service to validate the token and return username."""
    if not credentials:
        raise HTTPException(status_code=401, detail="No token provided")
    try:
        response = httpx.get(
            f"{AUTH_SERVICE_URL}/validate",
            headers={"Authorization": f"Bearer {credentials.credentials}"},
            timeout=5.0
        )
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid token")
        return response.json()["username"]
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Auth service unavailable")
    
# Routes
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "inventory"}

@app.get("/items")
def list_items(username: str = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, name, quantity, price, owner, created_at FROM items WHERE owner = %s", 
            (username,)
        )
        rows = cur.fetchall()
        return [
            {"id": r[0], "name": r[1], "quantity": r[2], "price": float(r[3]), "owner": r[4], "created_at": str(r[5])}
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()

@app.post("/items", status_code=201)
def create_item(item: Item, username: str = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO items (name, quantity, price, owner) VALUES (%s, %s, %s, %s) RETURNING id",
            (item.name, item.quantity, item.price, username)
        )
        item_id = cur.fetchone()[0]
        conn.commit()
        return {"id": item_id, "message": "Item created", "owner": username}
    finally:
        cur.close()
        conn.close()

@app.get("/items/{item_id}")
def get_item(item_id: int, username: str = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    try: 
        cur.execute(
            "SELECT id, name, quantity, price, owner, created_at FROM items WHERE id = %s AND owner = %s", 
            (item_id, username)
        )
        row = cur.fetchone()
        if not row: 
            raise HTTPException(status_code=404, detail="Item not found")
        return {"id": row[0], "name": row[1], "quantity": row[2],
                "price": float(row[3]), "owner": row[4], "created_at": str(row[5])}
    finally: 
        cur.close()
        conn.close()

@app.patch("/items/{item_id}")
def update_item(item_id: int, update: ItemUpdate, username: str = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    try: 
        fields, values = [], []
        if update.quantity is not None: 
            fields.append("quantity = %s"); 
            values.append(update.quantity)

        if update.price is not None: 
            fields.append("price = %s"); 
            values.append(update.price)

        if not fields: 
            raise HTTPException(status_code = 400, detail = "No fields to update")
        
        values += [item_id, username]
        cur.execute(
            f"UPDATE items SET {','.join(fields)} WHERE id = %s AND owner = %s RETURNING id",
            values
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail = "Item not found")
        conn.commit()
        return { "message": "Item updated"}
    finally: 
        cur.close()
        conn.close()

@app.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, username: str = Depends(get_current_user)): 
    conn = get_db()
    cur = conn.cursor()
    try: 
        cur.execute(
            "DELETE FROM items WHERE id = %s AND owner = %s RETURNING id",
            (item_id, username)
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, details="Item not found")
        conn.commit()
    finally:
        cur.close()
        conn.close()