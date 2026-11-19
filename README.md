<div align="center">

# SmartInventory

**Real-time inventory analytics engine — Python · PostgreSQL · FastAPI**

</div>

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-4169E1?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![pytest](https://img.shields.io/badge/tests-41%20passing-brightgreen?style=flat&logo=pytest)](tests/)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat)](LICENSE)

</div>

---

Inventory management and analytics backend built with raw PostgreSQL — no ORM, every query hand-written. Tracks products, suppliers, orders, and stock levels. When stock drops below the reorder threshold, a PL/pgSQL trigger fires and writes an alert row automatically. Analytics endpoints use window functions and CTEs to surface revenue trends, slow movers, and category rankings. Everything is served through a FastAPI REST API and a live Chart.js dashboard.

```
seed data → PostgreSQL schema + triggers → FastAPI REST API → analytics queries → live dashboard
```

---

## What's inside

| Layer | What it does |
|---|---|
| `db/schema.sql` | Tables, FK constraints, indexes, 2 PL/pgSQL triggers |
| `db/analytics.sql` | 6 standalone analytics queries for reference |
| `pipeline/seed.py` | Generates 20 products + 60 orders with psycopg2 |
| `api/main.py` | FastAPI app — CRUD endpoints + 5 analytics endpoints |
| `dashboard/index.html` | Chart.js dashboard, auto-refreshes every 30 s |
| `tests/` | 41 pytest tests — unit (mocked) + integration (real DB) |

---

## Quickstart

**Requires:** Python 3.11+, PostgreSQL 15+

```bash
git clone https://github.com/ansh44233/SmartInventory
cd SmartInventory

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

# create and apply schema
psql -U postgres -c "CREATE DATABASE smartinventory;"
psql -U postgres -d smartinventory -f db/schema.sql

# configure
copy .env.example .env        # then edit .env → add your postgres password

# seed
python pipeline/seed.py

# run
uvicorn api.main:app --reload
```

| URL | What you get |
|---|---|
| http://localhost:8000 | Live analytics dashboard |
| http://localhost:8000/docs | Interactive Swagger UI |

---

## API

### Products

```
GET    /products                   list (filter: ?category=  ?low_stock=true)
POST   /products                   create
PATCH  /products/{id}/stock        adjust stock (positive = restock, negative = deduct)
```

### Orders

```
GET    /orders                     list (filter: ?status=delivered)
POST   /orders                     place order — atomic, checks stock, snapshots price
```

### Analytics

```
GET    /analytics/revenue-by-product      top 10 products by revenue
GET    /analytics/monthly-trend           month-over-month revenue
GET    /analytics/slow-movers             no sales in last 30 days
GET    /analytics/supplier-performance    inventory value per supplier
GET    /analytics/alerts                  unresolved low-stock alerts
```

---

## SQL

<details>
<summary><strong>Trigger — automatic low-stock alert</strong></summary>

Fires on every `INSERT` or `UPDATE` to `products.stock_qty`. No application-side polling needed.

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

Stock is locked at the row level before deduction. Prevents overselling under concurrent requests.

```python
cur.execute(
    "SELECT unit_price, stock_qty FROM products WHERE id=%s FOR UPDATE",
    (item["product_id"],)
)
# check available stock → deduct → insert order_item, all in one transaction
# unit_price is snapshotted here — changing the product price later won't touch this order
```

</details>

---

## Tests

```bash
# unit tests — no database needed
pytest tests/ -m "not integration"

# full suite — needs postgres
set TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/smartinventory_test
pytest tests/ -v
```

| File | Tests | Type |
|---|---|---|
| `test_products.py` | 10 | Unit |
| `test_orders.py` | 8 | Unit |
| `test_analytics.py` | 13 | Unit |
| `test_integration_db.py` | 10 | Integration |

The integration tests create a real `smartinventory_test` database, run all assertions — including trigger verification, constraint checks, and analytics SQL — then drop it automatically.

---

## License

MIT © [Ansh](https://github.com/ansh44233)
