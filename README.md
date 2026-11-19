# SmartInventory

Inventory management + analytics backend I built to get better at raw SQL and PostgreSQL internals. No ORM, no magic — every query is written by hand.

The idea was simple: track products, suppliers, and orders, then answer business questions through SQL — revenue trends, slow movers, top sellers per category. Ended up going deeper than planned, adding PL/pgSQL triggers and a live dashboard.

---

## Stack

- **Python 3.11** — FastAPI, psycopg2, Pydantic v2
- **PostgreSQL 15** — raw SQL throughout, no SQLAlchemy
- **Chart.js** — frontend dashboard, plain HTML/JS
- **pytest** — unit + integration tests

---

## What it actually does

Products, categories, suppliers, orders, order line items — standard relational stuff. The interesting parts:

**Two database triggers:**

One fires whenever `stock_qty` drops below `reorder_level` — it writes a row to `stock_alerts` automatically. No polling from Python, the DB handles it.

```sql
CREATE OR REPLACE FUNCTION check_low_stock()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.stock_qty < NEW.reorder_level THEN
        INSERT INTO stock_alerts (product_id, alert_type)
        VALUES (NEW.id, 'low_stock')
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;
```

The second one keeps `updated_at` in sync on every product update — also a trigger, same pattern.

**Analytics queries using window functions:**

```sql
-- cumulative revenue month over month
SUM(SUM(oi.quantity * oi.unit_price))
    OVER (ORDER BY DATE_TRUNC('month', o.created_at))
AS cumulative_revenue
```

```sql
-- top 5 products per category
RANK() OVER (PARTITION BY c.id ORDER BY SUM(oi.quantity * oi.unit_price) DESC)
```

**Atomic order placement:**

Orders lock the product row with `SELECT FOR UPDATE` before deducting stock. Prevents overselling if two requests come in at the same time.

```python
cur.execute(
    "SELECT unit_price, stock_qty FROM products WHERE id=%s FOR UPDATE",
    (item["product_id"],)
)
# check stock → deduct → insert order_item, all in one transaction
```

Price is also snapshotted at order time into `order_items.unit_price` — changing a product's price later doesn't touch historical orders.

---

## Project structure

```
├── db/
│   ├── schema.sql       # all tables, indexes, triggers
│   └── analytics.sql    # standalone queries I use for reference
├── pipeline/
│   └── seed.py          # generates 20 products + 60 orders
├── api/
│   └── main.py          # FastAPI app — CRUD + 5 analytics endpoints
├── dashboard/
│   └── index.html       # live dashboard, auto-refreshes every 30s
├── tests/
│   ├── test_products.py
│   ├── test_orders.py
│   ├── test_analytics.py
│   └── test_integration_db.py   # tests the triggers + constraints directly
└── requirements.txt
```

---

## Running it locally

Needs Python 3.11+ and PostgreSQL 15+.

```bash
git clone https://github.com/ansh44233/SmartInventory
cd SmartInventory

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

# set up DB
psql -U postgres -c "CREATE DATABASE smartinventory;"
psql -U postgres -d smartinventory -f db/schema.sql

# copy the env file and add your postgres password
copy .env.example .env

# seed some data
python pipeline/seed.py

# start the server
uvicorn api.main:app --reload
```

Dashboard → http://localhost:8000  
API docs → http://localhost:8000/docs

---

## API endpoints

```
GET  /products                       list products (filter: ?category= ?low_stock=true)
POST /products                       add a product
PATCH /products/{id}/stock           adjust stock (delta can be negative)

GET  /orders                         list orders (filter: ?status=)
POST /orders                         place an order

GET  /analytics/revenue-by-product   top 10 by revenue
GET  /analytics/monthly-trend        month-over-month revenue
GET  /analytics/slow-movers          no sales in last 30 days
GET  /analytics/supplier-performance inventory value per supplier
GET  /analytics/alerts               unresolved low-stock alerts
```

---

## Tests

```bash
# unit tests — no DB needed, everything mocked
pytest tests/ -m "not integration"

# full suite — needs postgres
set TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/smartinventory_test
pytest tests/ -v
```

The integration tests spin up a real `smartinventory_test` database, run all assertions against it, then drop it. They cover the triggers directly — insert a product below reorder level, check that a `stock_alerts` row appears, that kind of thing.

---

## Notes

- `.env` is gitignored — only `.env.example` is committed
- The dashboard falls back to hardcoded demo data if the API isn't running, so it always looks right
- `analytics.sql` is just a reference file — the actual queries live in `api/main.py`
