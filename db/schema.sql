-- ============================================================
-- SmartInventory Schema
-- PostgreSQL  |  Raw SQL  |  No ORM
-- ============================================================

-- ── EXTENSIONS ──────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── TABLES ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS suppliers (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(150) UNIQUE NOT NULL,
    email       VARCHAR(200),
    phone       VARCHAR(30),
    country     VARCHAR(80),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR(50) UNIQUE NOT NULL,
    name            VARCHAR(200) NOT NULL,
    category_id     INT REFERENCES categories(id) ON DELETE SET NULL,
    supplier_id     INT REFERENCES suppliers(id) ON DELETE SET NULL,
    unit_price      NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    stock_qty       INT NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    reorder_level   INT NOT NULL DEFAULT 10,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    order_ref       VARCHAR(50) UNIQUE NOT NULL DEFAULT uuid_generate_v4()::TEXT,
    customer_name   VARCHAR(200) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','confirmed','shipped','delivered','cancelled')),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INT REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INT REFERENCES products(id) ON DELETE RESTRICT,
    quantity    INT NOT NULL CHECK (quantity > 0),
    unit_price  NUMERIC(12,2) NOT NULL,  -- snapshot at time of order
    UNIQUE (order_id, product_id)
);

CREATE TABLE IF NOT EXISTS stock_alerts (
    id          SERIAL PRIMARY KEY,
    product_id  INT REFERENCES products(id) ON DELETE CASCADE,
    alert_type  VARCHAR(30) NOT NULL DEFAULT 'low_stock',
    resolved    BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── INDEXES ──────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_supplier ON products(supplier_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order  ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_alerts_product ON stock_alerts(product_id);

-- ── TRIGGER: auto-update updated_at ──────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_products_updated_at ON products;
CREATE TRIGGER trg_products_updated_at
    BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ── TRIGGER: raise stock alert on low stock ──────────────────
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

DROP TRIGGER IF EXISTS trg_low_stock ON products;
CREATE TRIGGER trg_low_stock
    AFTER INSERT OR UPDATE OF stock_qty ON products
    FOR EACH ROW EXECUTE FUNCTION check_low_stock();
