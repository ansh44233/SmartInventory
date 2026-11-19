"""
SmartInventory  |  FastAPI REST + Analytics API
Run:  uvicorn api.main:app --reload
"""

import os
from contextlib import asynccontextmanager
from typing import Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ML forecasting (imported lazily to avoid startup errors if DB is offline)
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ml.forecasting import forecast_product, forecast_all

load_dotenv()
DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/smartinventory")


# ── DB helpers ───────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DSN)


def query(sql: str, params=None):
    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def execute(sql: str, params=None):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(sql, params or ())
    conn.commit()
    cur.close()
    conn.close()


# ── App ──────────────────────────────────────────────────────

app = FastAPI(
    title="SmartInventory API",
    description="Real-time inventory analytics backend — Python + PostgreSQL",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# serve dashboard HTML
app.mount("/static", StaticFiles(directory="dashboard"), name="static")


# ── Pydantic models ──────────────────────────────────────────

class ProductCreate(BaseModel):
    sku:          str
    name:         str
    category_id:  int
    supplier_id:  int
    unit_price:   float
    stock_qty:    int
    reorder_level: int = 10


class StockUpdate(BaseModel):
    delta: int   # positive = restock, negative = sale/adjustment


class OrderCreate(BaseModel):
    customer_name: str
    items: list[dict]   # [{"product_id": 1, "quantity": 2}, ...]


# ── PRODUCTS ─────────────────────────────────────────────────

@app.get("/products", tags=["Products"])
def list_products(
    category: Optional[str] = Query(None),
    low_stock: bool = Query(False),
):
    sql = """
        SELECT p.id, p.sku, p.name, c.name AS category,
               s.name AS supplier, p.unit_price,
               p.stock_qty, p.reorder_level,
               CASE WHEN p.stock_qty < p.reorder_level THEN true ELSE false END AS is_low_stock
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN suppliers  s ON s.id = p.supplier_id
        WHERE 1=1
    """
    params = []
    if category:
        sql += " AND c.name ILIKE %s"
        params.append(f"%{category}%")
    if low_stock:
        sql += " AND p.stock_qty < p.reorder_level"
    sql += " ORDER BY p.name"
    return query(sql, params)


@app.post("/products", status_code=201, tags=["Products"])
def create_product(body: ProductCreate):
    execute(
        """INSERT INTO products (sku,name,category_id,supplier_id,unit_price,stock_qty,reorder_level)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (body.sku, body.name, body.category_id, body.supplier_id,
         body.unit_price, body.stock_qty, body.reorder_level)
    )
    return {"message": "Product created."}


@app.patch("/products/{product_id}/stock", tags=["Products"])
def update_stock(product_id: int, body: StockUpdate):
    rows = query("SELECT stock_qty FROM products WHERE id=%s", (product_id,))
    if not rows:
        raise HTTPException(404, "Product not found")
    new_qty = rows[0]["stock_qty"] + body.delta
    if new_qty < 0:
        raise HTTPException(400, "Stock cannot go below 0")
    execute("UPDATE products SET stock_qty=%s WHERE id=%s", (new_qty, product_id))
    return {"product_id": product_id, "new_stock_qty": new_qty}


# ── ORDERS ───────────────────────────────────────────────────

@app.get("/orders", tags=["Orders"])
def list_orders(status: Optional[str] = None):
    sql = """
        SELECT o.id, o.order_ref, o.customer_name, o.status,
               o.created_at,
               COUNT(oi.id)                        AS item_count,
               SUM(oi.quantity * oi.unit_price)    AS order_total
        FROM orders o
        LEFT JOIN order_items oi ON oi.order_id = o.id
        WHERE 1=1
    """
    params = []
    if status:
        sql += " AND o.status = %s"
        params.append(status)
    sql += " GROUP BY o.id ORDER BY o.created_at DESC"
    return query(sql, params)


@app.post("/orders", status_code=201, tags=["Orders"])
def create_order(body: OrderCreate):
    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(
            "INSERT INTO orders (customer_name) VALUES (%s) RETURNING id, order_ref",
            (body.customer_name,)
        )
        order = cur.fetchone()
        for item in body.items:
            cur.execute("SELECT unit_price, stock_qty FROM products WHERE id=%s FOR UPDATE",
                        (item["product_id"],))
            prod = cur.fetchone()
            if not prod:
                raise HTTPException(404, f"Product {item['product_id']} not found")
            if prod["stock_qty"] < item["quantity"]:
                raise HTTPException(400, f"Insufficient stock for product {item['product_id']}")
            cur.execute(
                "INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES (%s,%s,%s,%s)",
                (order["id"], item["product_id"], item["quantity"], prod["unit_price"])
            )
            cur.execute(
                "UPDATE products SET stock_qty = stock_qty - %s WHERE id=%s",
                (item["quantity"], item["product_id"])
            )
        conn.commit()
        return {"order_id": order["id"], "order_ref": order["order_ref"]}
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


# ── ANALYTICS ────────────────────────────────────────────────

@app.get("/analytics/revenue-by-product", tags=["Analytics"])
def revenue_by_product():
    return query("""
        SELECT p.sku, p.name, c.name AS category,
               SUM(oi.quantity)                    AS units_sold,
               SUM(oi.quantity * oi.unit_price)    AS total_revenue
        FROM order_items oi
        JOIN products p  ON p.id  = oi.product_id
        JOIN categories c ON c.id = p.category_id
        JOIN orders o    ON o.id  = oi.order_id
        WHERE o.status NOT IN ('cancelled')
        GROUP BY p.sku, p.name, c.name
        ORDER BY total_revenue DESC
        LIMIT 10
    """)


@app.get("/analytics/monthly-trend", tags=["Analytics"])
def monthly_trend():
    return query("""
        SELECT
            TO_CHAR(DATE_TRUNC('month', o.created_at), 'Mon YYYY') AS month,
            SUM(oi.quantity * oi.unit_price)                        AS revenue
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id
        WHERE o.status NOT IN ('cancelled')
        GROUP BY DATE_TRUNC('month', o.created_at)
        ORDER BY DATE_TRUNC('month', o.created_at)
    """)


@app.get("/analytics/slow-movers", tags=["Analytics"])
def slow_movers():
    return query("""
        SELECT p.id, p.sku, p.name, p.stock_qty, p.unit_price
        FROM products p
        WHERE p.id NOT IN (
            SELECT DISTINCT oi.product_id
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.created_at >= NOW() - INTERVAL '30 days'
        )
        ORDER BY p.stock_qty DESC
        LIMIT 10
    """)


@app.get("/analytics/supplier-performance", tags=["Analytics"])
def supplier_performance():
    return query("""
        SELECT s.name AS supplier,
               COUNT(DISTINCT p.id)               AS products_supplied,
               SUM(p.stock_qty * p.unit_price)    AS inventory_value
        FROM suppliers s
        JOIN products p ON p.supplier_id = s.id
        GROUP BY s.name
        ORDER BY inventory_value DESC
    """)


@app.get("/analytics/alerts", tags=["Analytics"])
def active_alerts():
    return query("""
        SELECT sa.id, p.sku, p.name, p.stock_qty, p.reorder_level,
               sa.alert_type, sa.created_at
        FROM stock_alerts sa
        JOIN products p ON p.id = sa.product_id
        WHERE sa.resolved = FALSE
        ORDER BY sa.created_at DESC
    """)


# ── FORECASTING ──────────────────────────────────────────────

@app.get("/analytics/forecast/{product_id}", tags=["Forecasting"])
def forecast_product_endpoint(
    product_id: int,
    days: int = Query(default=30, ge=1, le=90, description="Forecast horizon in days"),
):
    """
    ML demand forecast for a single product.
    Uses polynomial Ridge regression trained on order history.
    Returns daily predicted demand + 80% confidence bounds + restock alert.
    """
    try:
        result = forecast_product(product_id, horizon_days=days)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Forecast error: {str(e)}")

    return {
        "product_id":        result.product_id,
        "product_name":      result.product_name,
        "sku":               result.sku,
        "history_days":      result.history_days,
        "avg_daily_demand":  result.avg_daily_demand,
        "model_mae":         result.model_mae,
        "restock_alert":     result.restock_alert,
        "forecast": [
            {
                "date":          fp.date,
                "predicted_qty": fp.predicted_qty,
                "lower":         fp.lower,
                "upper":         fp.upper,
            }
            for fp in result.forecast
        ],
    }


@app.get("/analytics/forecast", tags=["Forecasting"])
def forecast_all_products(
    days: int = Query(default=30, ge=1, le=90),
):
    """
    Summary forecast for all products — total 30-day projected demand,
    avg daily demand, restock alerts, and model MAE for each product.
    """
    try:
        return forecast_all(horizon_days=days)
    except Exception as e:
        raise HTTPException(500, f"Forecast error: {str(e)}")


# ── DASHBOARD ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_dashboard():
    with open("dashboard/index.html", "r", encoding="utf-8") as f:
        return f.read()
