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

## Example

Place an order and watch stock deduct + alert fire:

```bash
# 1. add a product with low reorder threshold
curl -X POST http://localhost:8000/products \
  -H "Content-Type: application/json" \
  -d '{
    "sku": "SKU-DEMO",
    "name": "Wireless Mouse",
    "category_id": 1,
    "supplier_id": 1,
    "unit_price": 799,
    "stock_qty": 12,
    "reorder_level": 10
  }'

# 2. place an order that brings stock below the threshold
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "customer_name": "Rahul Sharma",
    "items": [{"product_id": 1, "quantity": 5}]
  }'
# → {"order_id": 1, "order_ref": "abc-123"}
# → stock drops to 7, PostgreSQL trigger fires, alert row written automatically

# 3. check alerts — no polling, trigger already did it
curl http://localhost:8000/analytics/alerts
# → [{"sku": "SKU-DEMO", "name": "Wireless Mouse", "stock_qty": 7, "reorder_level": 10, "alert_type": "low_stock"}]

# 4. restock
curl -X PATCH http://localhost:8000/products/1/stock \
  -H "Content-Type: application/json" \
  -d '{"delta": 50}'
# → {"product_id": 1, "new_stock_qty": 57}
```

Revenue analytics after a few orders:

```bash
curl http://localhost:8000/analytics/revenue-by-product
# → [
#     {"sku": "SKU-0015", "name": "Smart Watch Gen2", "category": "Electronics", "units_sold": 12, "total_revenue": 71988},
#     {"sku": "SKU-0009", "name": "Air Fryer 4L",     "category": "Home & Kitchen", "units_sold": 6, "total_revenue": 23994},
#     ...
#   ]

curl http://localhost:8000/analytics/monthly-trend
# → [
#     {"month": "Sep 2026", "revenue": 18400},
#     {"month": "Oct 2026", "revenue": 34200},
#     {"month": "Nov 2026", "revenue": 41800}
#   ]
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Client                             │
│          Browser (dashboard) · curl · any HTTP          │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────────┐
│                   FastAPI (api/main.py)                  │
│                                                         │
│  /products   /orders   /analytics/*   /  (dashboard)    │
│                                                         │
│  Pydantic v2 models · psycopg2 · plain SQL queries      │
└──────────────────────┬──────────────────────────────────┘
                       │ psycopg2 (raw SQL)
┌──────────────────────▼──────────────────────────────────┐
│                  PostgreSQL 15                           │
│                                                         │
│  categories ──┐                                         │
│  suppliers  ──┼──► products ──► order_items ◄── orders  │
│                              │                          │
│                              ▼                          │
│                        stock_alerts                     │
│                     (written by trigger)                │
│                                                         │
│  Triggers:  trg_low_stock · trg_products_updated_at     │
│  Indexes:   category, supplier, order_id, product_id    │
└─────────────────────────────────────────────────────────┘
```

**Data flow for an order:**

```
POST /orders
  │
  ├─ BEGIN transaction
  ├─ SELECT ... FOR UPDATE   (lock product row)
  ├─ check stock_qty >= quantity
  ├─ INSERT order_items      (snapshot unit_price)
  ├─ UPDATE products.stock_qty -= quantity
  │     └─ trg_low_stock fires if stock_qty < reorder_level
  │           └─ INSERT stock_alerts (automatic, no app code)
  └─ COMMIT
```

---

## Roadmap

Things I'm planning to add:

- [ ] **Demand forecasting** — ML model (linear regression / ARIMA) on order history to predict restock dates
- [ ] **WebSocket alerts** — push low-stock notifications to the dashboard in real time instead of polling
- [ ] **Multi-warehouse support** — `warehouses` table, stock split across locations
- [ ] **Supplier lead time tracking** — record expected delivery days per supplier, factor into reorder suggestions
- [ ] **CSV export** — download any analytics view as a spreadsheet
- [ ] **Auth** — JWT-based login so the API isn't open by default
- [ ] **Docker + docker-compose** — one-command local setup without installing Postgres manually

PRs for any of these are welcome.

---

## Contributing

1. Fork the repo and create a branch off `initial-release`

   ```bash
   git checkout -b feat/your-feature
   ```

2. Make your changes. If you're touching the DB layer, update `db/schema.sql` and add a migration note in your PR description.

3. Run tests before pushing:

   ```bash
   pytest tests/ -m "not integration"
   ```

4. Open a pull request against `initial-release`. Describe what changed and why.

**Good first issues:**
- Add Docker + docker-compose setup
- Add a `/products/{id}` GET endpoint
- Add CSV export to any analytics endpoint
- Write more integration tests for the analytics queries

---

## Star History

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=ansh44233/SmartInventory&type=Date)](https://star-history.com/#ansh44233/SmartInventory&Date)

</div>

---

## License

MIT © [Ansh](https://github.com/ansh44233)
