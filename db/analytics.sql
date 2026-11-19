-- ============================================================
-- SmartInventory  |  Analytics Queries
-- ============================================================

-- 1. Revenue by product (all time)
SELECT
    p.sku,
    p.name,
    c.name                              AS category,
    SUM(oi.quantity)                    AS units_sold,
    SUM(oi.quantity * oi.unit_price)    AS total_revenue
FROM order_items oi
JOIN products p  ON p.id  = oi.product_id
JOIN categories c ON c.id = p.category_id
JOIN orders o    ON o.id  = oi.order_id
WHERE o.status NOT IN ('cancelled')
GROUP BY p.sku, p.name, c.name
ORDER BY total_revenue DESC;


-- 2. Monthly revenue trend (window function)
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


-- 3. Slow movers — products with zero orders in last 30 days
SELECT
    p.id, p.sku, p.name, p.stock_qty, p.unit_price,
    COALESCE(last_sale.last_ordered, 'never') AS last_ordered
FROM products p
LEFT JOIN (
    SELECT oi.product_id,
           MAX(o.created_at)::TEXT AS last_ordered
    FROM order_items oi
    JOIN orders o ON o.id = oi.order_id
    WHERE o.created_at >= NOW() - INTERVAL '30 days'
    GROUP BY oi.product_id
) last_sale ON last_sale.product_id = p.id
WHERE last_sale.product_id IS NULL
ORDER BY p.stock_qty DESC;


-- 4. Supplier performance — avg fulfilment value
SELECT
    s.name                              AS supplier,
    COUNT(DISTINCT p.id)               AS products_supplied,
    SUM(p.stock_qty * p.unit_price)    AS inventory_value
FROM suppliers s
JOIN products p ON p.supplier_id = s.id
GROUP BY s.name
ORDER BY inventory_value DESC;


-- 5. Top 5 products per category (RANK window function)
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
    JOIN categories c    ON c.id  = p.category_id
    JOIN order_items oi  ON oi.product_id = p.id
    JOIN orders o        ON o.id  = oi.order_id
    WHERE o.status NOT IN ('cancelled')
    GROUP BY p.name, c.name, c.id
)
SELECT * FROM ranked WHERE rnk <= 5;


-- 6. Active stock alerts (unresolved)
SELECT
    sa.id,
    p.sku, p.name,
    p.stock_qty, p.reorder_level,
    sa.alert_type,
    sa.created_at
FROM stock_alerts sa
JOIN products p ON p.id = sa.product_id
WHERE sa.resolved = FALSE
ORDER BY sa.created_at DESC;
