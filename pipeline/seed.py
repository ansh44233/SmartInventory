"""
SmartInventory — Seed Pipeline
Generates realistic fake data and loads it into PostgreSQL.
Run:  python pipeline/seed.py
"""

import os
import random
import psycopg2
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/smartinventory")

CATEGORIES = ["Electronics", "Apparel", "Home & Kitchen", "Sports", "Books", "Toys"]

SUPPLIERS = [
    ("TechSource Ltd",    "tech@techsource.com",  "+1-800-111-2222", "USA"),
    ("GlobalGoods Inc",   "info@globalgoods.io",  "+44-20-7946-0958","UK"),
    ("AsiaTrade Co",      "sales@asiatrade.cn",   "+86-21-5555-6666","China"),
    ("EuroParts GmbH",    "eu@europarts.de",      "+49-30-9999-0000","Germany"),
    ("LocalSupply Pvt",   "hello@localsupply.in", "+91-80-4444-5555","India"),
]

PRODUCT_TEMPLATES = [
    ("Wireless Earbuds Pro",   "Electronics",  2499, 150),
    ("USB-C Hub 7-Port",       "Electronics",   899,  80),
    ("Mechanical Keyboard",    "Electronics",  3499,  40),
    ("Running Shoes X3",       "Sports",       1999,  60),
    ("Yoga Mat Premium",       "Sports",        599, 100),
    ("Cotton T-Shirt (M)",     "Apparel",       299, 200),
    ("Denim Jeans Slim Fit",   "Apparel",       799,  90),
    ("Non-Stick Cookware Set", "Home & Kitchen",1299,  35),
    ("Air Fryer 4L",           "Home & Kitchen",3999,  20),
    ("LEGO City Set",          "Toys",          999,  55),
    ("Remote Control Car",     "Toys",         1499,  45),
    ("Python Crash Course",    "Books",          499, 120),
    ("Clean Code",             "Books",          699,  75),
    ("Bluetooth Speaker",      "Electronics",  1799,  65),
    ("Smart Watch Gen2",       "Electronics",  5999,  30),
    ("Resistance Bands Kit",   "Sports",        349, 110),
    ("Water Bottle 1L",        "Sports",        249, 180),
    ("Ceramic Mug Set",        "Home & Kitchen", 349, 140),
    ("Board Game Catan",       "Toys",          2499,  25),
    ("Data Structures Book",   "Books",          599,  85),
]

CUSTOMERS = [
    "Rahul Sharma", "Priya Patel", "Arjun Nair", "Sneha Reddy",
    "Vikram Singh", "Anjali Mehta", "Rohan Gupta", "Kavya Iyer",
    "Amit Joshi",   "Deepa Pillai",
]

ORDER_STATUSES = ["pending","confirmed","shipped","delivered","cancelled"]


def connect():
    return psycopg2.connect(DSN)


def seed(conn):
    cur = conn.cursor()

    # categories
    cat_map = {}
    for name in CATEGORIES:
        cur.execute(
            "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id",
            (name,)
        )
        cat_map[name] = cur.fetchone()[0]

    # suppliers
    sup_ids = []
    for s in SUPPLIERS:
        cur.execute(
            """INSERT INTO suppliers (name,email,phone,country)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (name) DO UPDATE SET email=EXCLUDED.email
               RETURNING id""",
            s
        )
        sup_ids.append(cur.fetchone()[0])

    # products
    prod_ids = []
    for i, (pname, cat, price, qty) in enumerate(PRODUCT_TEMPLATES):
        sku = f"SKU-{(i+1):04d}"
        reorder = random.randint(5, 20)
        cur.execute(
            """INSERT INTO products (sku,name,category_id,supplier_id,unit_price,stock_qty,reorder_level)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (sku) DO UPDATE SET stock_qty=EXCLUDED.stock_qty
               RETURNING id""",
            (sku, pname, cat_map[cat], random.choice(sup_ids), price, qty, reorder)
        )
        prod_ids.append(cur.fetchone()[0])

    # orders  (60 orders, 1-4 items each, spread over last 90 days)
    for _ in range(60):
        customer = random.choice(CUSTOMERS)
        status   = random.choices(ORDER_STATUSES, weights=[5,10,20,55,10])[0]
        days_ago = random.randint(0, 90)
        order_dt = datetime.now() - timedelta(days=days_ago)

        cur.execute(
            """INSERT INTO orders (customer_name, status, created_at)
               VALUES (%s,%s,%s) RETURNING id""",
            (customer, status, order_dt)
        )
        order_id = cur.fetchone()[0]

        items = random.sample(prod_ids, k=random.randint(1,4))
        for pid in items:
            qty = random.randint(1,5)
            # fetch current unit_price as snapshot
            cur.execute("SELECT unit_price FROM products WHERE id=%s", (pid,))
            price = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO order_items (order_id,product_id,quantity,unit_price)
                   VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (order_id, pid, qty, price)
            )

    conn.commit()
    cur.close()
    print(f"✅  Seeded: {len(CATEGORIES)} categories, {len(SUPPLIERS)} suppliers, "
          f"{len(PRODUCT_TEMPLATES)} products, 60 orders.")


if __name__ == "__main__":
    conn = connect()
    seed(conn)
    conn.close()
