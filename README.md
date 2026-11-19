<div align="center">

# 📦 SmartInventory

**Real-time inventory analytics engine — Python · PostgreSQL · FastAPI**

A production-grade backend system built from first principles: raw SQL, PL/pgSQL triggers, window functions, atomic transactions, a REST API, and a live analytics dashboard.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-4169E1?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![pytest](https://img.shields.io/badge/tests-41%20passing-brightgreen?style=flat&logo=pytest)](tests/)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat)](LICENSE)

</div>

---

## What it does

SmartInventory tracks products, suppliers, orders, and stock levels in real time. When stock drops below the reorder threshold, a PostgreSQL trigger fires automatically — no application polling. The analytics layer uses window functions and CTEs to surface revenue trends, slow movers, and supplier performance. Everything is exposed via a typed FastAPI REST API and a live Chart.js dashboard that refreshes every 30 seconds.

---

## Demo

| Dashboard | Swagger UI |
|---|---|
| `http://localhost:8000` | `http://localhost:8000/docs` |

<img src="https://raw.githubusercontent.com/ansh44233/SmartInventory/main/dashboard/preview.png" alt="Dashboard preview" width="700"/>

---

## Architecture

```
SmartInventory/
├── db/
│   ├── schema.sql          ← tables, indexes, FK constraints, 2 PL/pgSQL triggers
│   └── analytics.sql       ← 6 standalone analytics queries (window fns, CTEs)
├── pipeline/
│   └── seed.py             ← generates 20 products + 60 orders with psycopg2
├── api/
│   └── main.py             ← FastAPI app: CRUD + 5 analytics endpoints
├── dashboard/
│   └── index.html          ← Chart.js live dashboard (auto-refresh 30s)
├── tests/
│   ├── conftest.py         ← shared fixtures, test DB lifecycle
│   ├── test_products.py    ← 10 unit tests
│   ├── test_orders.py      ← 8 unit tests
│   ├── test_analytics.py   ← 13 unit tests
│   └── test_integration_db.py ← 10 integration tests (triggers, constraints, SQL)
├── requirements.txt
└── .env.example
```

---

## Quick Start

**Prerequisites:** Python 3.11+, PostgreSQL 15+

```bash
# 1 — clone and enter
git clone https://github.com/ansh44233/SmartInventory.git
cd SmartInventory

# 2 — virtual env
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 3 — install dependencies
pip install -r requirements.txt

# 4 — configure database
copy .env.example .env
# open .env and set your PostgreSQL password

# 5 — create DB and apply schema
psql -U postgres -c "CREATE DATABASE smartinventory;"
psql -U postgres -d smartinventory -f db/schema.sql

# 6 — seed realistic data
python pipeline/seed.py

# 7 — start the API
uvicorn api.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) for the dashboard.  
Open [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive API docs.

---

## API Reference

### Products

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/products` | List all products (filter: `?category=`, `?low_stock=true`) |
| `POST` | `/products` | Create a product |
| `PATCH` | `/products/{id}/stock` | Adjust stock (`delta`: positive = restock, negative = sale) |

### Orders

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/orders` | List orders (filter: `?status=delivered`) |
| `POST` | `/orders` | Place an order — atomic, checks stock, snapshots price |

### Analytics

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/analytics/revenue-by-product` | Top 10 products by revenue |
| `GET` | `/analytics/monthly-trend` | Monthly revenue over time |
| `GET` | `/analytics/slow-movers` | Products with no sales in 30 days |
| `GET` | `/analytics/supplier-performance` | Inventory value per supplier |
| `GET` | `/analytics/alerts` | Active unresolved low-stock alerts |

---

## SQL Deep Dives

<details>
<summary><strong>PL/pgSQL trigger — automatic low-stock alert</strong></summary>

Fires on every `INSERT` or `UPDATE` to `products.stock_qty`. No application code needed.

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

CREATE TRIGGER trg_low_stock
    AFTER INSERT OR UPDATE OF stock_qty ON products
    FOR EACH ROW EXECUTE FUNCTION check_low_stock();
```
</details>

<details>
<summary><strong>Window function — cumulative monthly revenue</strong></summary>

```sql
SELECT
    DATE_TRUNC('month', o.created_at)   AS month,
    SUM(oi.quantity * oi.unit_price)    AS revenue,
    SUM(SUM(oi.quantity * oi.unit_price))
        OVER (ORDER BY DATE_TRUNC('month', o.created_at))
                                        AS cumulative_revenue
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
WHERE o.status NOT IN ('cancelled')
GROUP BY month
ORDER BY month;
```
</details>

<details>
<summary><strong>CTE + RANK — top 5 products per category</strong></summary>

```sql
WITH ranked AS (
    SELECT
        p.name,
        c.name                              AS category,
        SUM(oi.quantity * oi.unit_price)    AS revenue,
        RANK() OVER (
            PARTITION BY c.id
            ORDER BY SUM(oi.quantity * oi.unit_price) DESC
        ) AS rnk
    FROM products p
    JOIN categories c   ON c.id = p.category_id
    JOIN order_items oi ON oi.product_id = p.id
    JOIN orders o       ON o.id = oi.order_id
    WHERE o.status NOT IN ('cancelled')
    GROUP BY p.name, c.name, c.id
)
SELECT * FROM ranked WHERE rnk <= 5;
```
</details>

<details>
<summary><strong>Atomic order placement — SELECT FOR UPDATE</strong></summary>

Stock is locked at the row level before deduction. No race condition, no overselling.

```python
cur.execute(
    "SELECT unit_price, stock_qty FROM products WHERE id=%s FOR UPDATE",
    (product_id,)
)
# check stock, deduct, insert order_item — all in one transaction
```
</details>

---

## Tests

```bash
# Unit tests only (no database needed)
pytest tests/ -m "not integration"

# Full suite including integration tests (needs PostgreSQL)
set TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/smartinventory_test
pytest tests/ -v
```

| File | Tests | Type |
|---|---|---|
| `test_products.py` | 10 | Unit — list, create, stock update, 404/400 |
| `test_orders.py` | 8 | Unit — list, create, insufficient stock, not found |
| `test_analytics.py` | 13 | Unit — all 5 endpoints, field checks, empty states |
| `test_integration_db.py` | 10 | Integration — triggers, constraints, analytics SQL |

Integration tests spin up a real `smartinventory_test` database, run all assertions, then drop it automatically.

---

## Tech Stack

| Layer | Tech |
|---|---|
| Language | Python 3.11 |
| Database | PostgreSQL 15 — raw SQL, no ORM |
| DB driver | psycopg2 |
| API | FastAPI + Pydantic v2 |
| Dashboard | Chart.js + vanilla JS |
| Testing | pytest + FastAPI TestClient |
| Config | python-dotenv |

---

## License

MIT © [Ansh](https://github.com/ansh44233)
