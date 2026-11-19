"""
Integration tests  —  require a live PostgreSQL instance.

Set env var before running:
    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/smartinventory_test

Run:
    pytest tests/test_integration_db.py -m integration -v
"""

import pytest
import psycopg2
import psycopg2.extras
import os

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_tables(test_db):
    """Wipe all data between tests (FK order matters)."""
    cur = test_db.cursor()
    cur.execute("""
        TRUNCATE stock_alerts, order_items, orders, products, suppliers, categories
        RESTART IDENTITY CASCADE
    """)
    test_db.commit()
    cur.close()


def insert_category(conn, name="Electronics"):
    cur = conn.cursor()
    cur.execute("INSERT INTO categories (name) VALUES (%s) RETURNING id", (name,))
    cid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return cid


def insert_supplier(conn, name="TechCo"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO suppliers (name,email,country) VALUES (%s,%s,%s) RETURNING id",
        (name, "test@test.com", "India")
    )
    sid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return sid


def insert_product(conn, cat_id, sup_id, sku="TST-001", qty=100, reorder=10):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO products (sku,name,category_id,supplier_id,unit_price,stock_qty,reorder_level)
           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (sku, "Test Product", cat_id, sup_id, 999.0, qty, reorder)
    )
    pid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return pid


# ── Schema tests ─────────────────────────────────────────────

class TestSchema:
    def test_all_tables_exist(self, test_db):
        cur = test_db.cursor()
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        tables = {r[0] for r in cur.fetchall()}
        cur.close()
        for t in ("categories","suppliers","products","orders","order_items","stock_alerts"):
            assert t in tables, f"Missing table: {t}"

    def test_products_unique_sku(self, test_db):
        cat = insert_category(test_db)
        sup = insert_supplier(test_db)
        insert_product(test_db, cat, sup, sku="DUP-001")
        cur = test_db.cursor()
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                """INSERT INTO products (sku,name,category_id,supplier_id,unit_price,stock_qty)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                ("DUP-001","Duplicate",cat,sup,100.0,10)
            )
        test_db.rollback()
        cur.close()

    def test_stock_qty_cannot_be_negative(self, test_db):
        cat = insert_category(test_db)
        sup = insert_supplier(test_db)
        cur = test_db.cursor()
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """INSERT INTO products (sku,name,category_id,supplier_id,unit_price,stock_qty)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                ("NEG-001","Bad Product",cat,sup,100.0,-1)
            )
        test_db.rollback()
        cur.close()


# ── Trigger tests ────────────────────────────────────────────

class TestTriggers:
    def test_low_stock_trigger_fires(self, test_db):
        """Inserting a product below reorder_level should create a stock_alert."""
        cat = insert_category(test_db)
        sup = insert_supplier(test_db)
        pid = insert_product(test_db, cat, sup, qty=5, reorder=10)  # 5 < 10 → alert

        cur = test_db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM stock_alerts WHERE product_id=%s", (pid,))
        alerts = cur.fetchall()
        cur.close()
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "low_stock"

    def test_no_alert_when_stock_ok(self, test_db):
        cat = insert_category(test_db)
        sup = insert_supplier(test_db)
        pid = insert_product(test_db, cat, sup, qty=100, reorder=10)  # ok

        cur = test_db.cursor()
        cur.execute("SELECT COUNT(*) FROM stock_alerts WHERE product_id=%s", (pid,))
        count = cur.fetchone()[0]
        cur.close()
        assert count == 0

    def test_trigger_fires_on_stock_update(self, test_db):
        cat = insert_category(test_db)
        sup = insert_supplier(test_db)
        pid = insert_product(test_db, cat, sup, qty=50, reorder=10)  # ok initially

        # Deduct stock below reorder level
        cur = test_db.cursor()
        cur.execute("UPDATE products SET stock_qty=3 WHERE id=%s", (pid,))
        test_db.commit()
        cur.execute("SELECT COUNT(*) FROM stock_alerts WHERE product_id=%s AND resolved=FALSE", (pid,))
        count = cur.fetchone()[0]
        cur.close()
        assert count >= 1

    def test_updated_at_trigger(self, test_db):
        cat = insert_category(test_db)
        sup = insert_supplier(test_db)
        pid = insert_product(test_db, cat, sup)

        cur = test_db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT updated_at FROM products WHERE id=%s", (pid,))
        before = cur.fetchone()["updated_at"]

        import time; time.sleep(0.05)
        cur.execute("UPDATE products SET name='Updated Name' WHERE id=%s", (pid,))
        test_db.commit()

        cur.execute("SELECT updated_at FROM products WHERE id=%s", (pid,))
        after = cur.fetchone()["updated_at"]
        cur.close()
        assert after > before


# ── Business logic tests ─────────────────────────────────────

class TestOrderLogic:
    def test_order_deducts_stock(self, test_db):
        cat = insert_category(test_db)
        sup = insert_supplier(test_db)
        pid = insert_product(test_db, cat, sup, qty=50)

        cur = test_db.cursor()
        cur.execute(
            "INSERT INTO orders (customer_name) VALUES (%s) RETURNING id",
            ("Test Customer",)
        )
        oid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES (%s,%s,%s,%s)",
            (oid, pid, 10, 999.0)
        )
        cur.execute("UPDATE products SET stock_qty = stock_qty - 10 WHERE id=%s", (pid,))
        test_db.commit()

        cur.execute("SELECT stock_qty FROM products WHERE id=%s", (pid,))
        assert cur.fetchone()[0] == 40
        cur.close()

    def test_order_item_snapshots_price(self, test_db):
        """Unit price in order_items should be independent of product price changes."""
        cat = insert_category(test_db)
        sup = insert_supplier(test_db)
        pid = insert_product(test_db, cat, sup)

        cur = test_db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("INSERT INTO orders (customer_name) VALUES (%s) RETURNING id", ("Snapshot Test",))
        oid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES (%s,%s,%s,%s)",
            (oid, pid, 1, 999.0)   # snapshot at 999
        )
        # Change product price
        cur.execute("UPDATE products SET unit_price=5000.0 WHERE id=%s", (pid,))
        test_db.commit()

        cur.execute("SELECT unit_price FROM order_items WHERE order_id=%s", (oid,))
        assert float(cur.fetchone()["unit_price"]) == 999.0   # still the old price
        cur.close()

    def test_analytics_revenue_query(self, test_db):
        cat = insert_category(test_db, "Electronics")
        sup = insert_supplier(test_db)
        pid = insert_product(test_db, cat, sup, qty=100)

        cur = test_db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("INSERT INTO orders (customer_name, status) VALUES (%s,%s) RETURNING id",
                    ("Analytics User","delivered"))
        oid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES (%s,%s,%s,%s)",
            (oid, pid, 5, 999.0)
        )
        test_db.commit()

        cur.execute("""
            SELECT SUM(oi.quantity * oi.unit_price) AS total_revenue
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.status NOT IN ('cancelled')
        """)
        revenue = float(cur.fetchone()["total_revenue"])
        cur.close()
        assert revenue == 4995.0
