"""
Tests for /orders endpoints.
"""

import pytest
from unittest.mock import patch, MagicMock

MOCK_ORDERS = [
    {
        "id": 1, "order_ref": "abc-123", "customer_name": "Rahul Sharma",
        "status": "delivered", "created_at": "2026-10-01T10:00:00",
        "item_count": 2, "order_total": 5000.0,
    },
    {
        "id": 2, "order_ref": "def-456", "customer_name": "Priya Patel",
        "status": "pending", "created_at": "2026-10-15T14:30:00",
        "item_count": 1, "order_total": 2499.0,
    },
]


class TestListOrders:
    def test_returns_list(self, client):
        with patch("api.main.query", return_value=MOCK_ORDERS):
            resp = client.get("/orders")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_order_has_required_fields(self, client):
        with patch("api.main.query", return_value=MOCK_ORDERS):
            resp = client.get("/orders")
        item = resp.json()[0]
        for field in ("id", "order_ref", "customer_name", "status"):
            assert field in item

    def test_status_filter_delivered(self, client):
        delivered = [o for o in MOCK_ORDERS if o["status"] == "delivered"]
        with patch("api.main.query", return_value=delivered):
            resp = client.get("/orders?status=delivered")
        assert resp.status_code == 200
        for o in resp.json():
            assert o["status"] == "delivered"

    def test_empty_orders(self, client):
        with patch("api.main.query", return_value=[]):
            resp = client.get("/orders")
        assert resp.json() == []


class TestCreateOrder:
    def _make_mock_conn(self, product_price=999.0, product_stock=50):
        """Build a mock psycopg2 connection that returns realistic data."""
        mock_conn = MagicMock()
        mock_cur  = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Simulate: INSERT orders RETURNING id, order_ref
        mock_cur.fetchone.side_effect = [
            {"id": 42, "order_ref": "test-ref-001"},   # order insert
            {"unit_price": product_price, "stock_qty": product_stock},  # product fetch
        ]
        return mock_conn, mock_cur

    def test_create_order_success(self, client):
        mock_conn, mock_cur = self._make_mock_conn()
        with patch("api.main.get_conn", return_value=mock_conn):
            resp = client.post("/orders", json={
                "customer_name": "Test User",
                "items": [{"product_id": 1, "quantity": 2}],
            })
        assert resp.status_code == 201
        body = resp.json()
        assert "order_id" in body
        assert "order_ref" in body

    def test_missing_customer_name(self, client):
        resp = client.post("/orders", json={"items": [{"product_id": 1, "quantity": 1}]})
        assert resp.status_code == 422

    def test_empty_items_list(self, client):
        # Empty items — order is created with no line items (valid at API level)
        mock_conn, mock_cur = self._make_mock_conn()
        mock_cur.fetchone.side_effect = [{"id": 10, "order_ref": "empty-ref"}]
        with patch("api.main.get_conn", return_value=mock_conn):
            resp = client.post("/orders", json={
                "customer_name": "Test User",
                "items": [],
            })
        assert resp.status_code == 201

    def test_insufficient_stock_returns_400(self, client):
        mock_conn, mock_cur = self._make_mock_conn(product_stock=1)
        # fetchone: order created, then product with stock=1
        mock_cur.fetchone.side_effect = [
            {"id": 99, "order_ref": "low-stock-ref"},
            {"unit_price": 500.0, "stock_qty": 1},
        ]
        with patch("api.main.get_conn", return_value=mock_conn):
            resp = client.post("/orders", json={
                "customer_name": "Test User",
                "items": [{"product_id": 1, "quantity": 100}],
            })
        assert resp.status_code == 400
        assert "stock" in resp.json()["detail"].lower()

    def test_product_not_found_returns_404(self, client):
        mock_conn, mock_cur = self._make_mock_conn()
        mock_cur.fetchone.side_effect = [
            {"id": 55, "order_ref": "noprod-ref"},
            None,   # product not found
        ]
        with patch("api.main.get_conn", return_value=mock_conn):
            resp = client.post("/orders", json={
                "customer_name": "Test User",
                "items": [{"product_id": 9999, "quantity": 1}],
            })
        assert resp.status_code == 404
