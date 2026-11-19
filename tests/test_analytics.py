"""
Tests for /analytics/* endpoints.
"""

import pytest
from unittest.mock import patch

MOCK_REVENUE = [
    {"sku": "SKU-0001", "name": "Earbuds", "category": "Electronics",
     "units_sold": 20, "total_revenue": 49980.0},
    {"sku": "SKU-0002", "name": "Yoga Mat", "category": "Sports",
     "units_sold": 10, "total_revenue": 5990.0},
]

MOCK_TREND = [
    {"month": "Sep 2026", "revenue": 25000.0},
    {"month": "Oct 2026", "revenue": 38000.0},
]

MOCK_ALERTS = [
    {"id": 1, "sku": "SKU-0003", "name": "Air Fryer", "stock_qty": 2,
     "reorder_level": 10, "alert_type": "low_stock", "created_at": "2026-11-01"},
]

MOCK_SLOW = [
    {"id": 5, "sku": "SKU-0005", "name": "Board Game", "stock_qty": 25, "unit_price": 2499.0},
]

MOCK_SUPPLIERS = [
    {"supplier": "TechSource Ltd", "products_supplied": 5, "inventory_value": 500000.0},
]


class TestRevenueByProduct:
    def test_returns_list(self, client):
        with patch("api.main.query", return_value=MOCK_REVENUE):
            resp = client.get("/analytics/revenue-by-product")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_has_revenue_field(self, client):
        with patch("api.main.query", return_value=MOCK_REVENUE):
            resp = client.get("/analytics/revenue-by-product")
        for item in resp.json():
            assert "total_revenue" in item
            assert "units_sold" in item

    def test_sorted_descending_by_revenue(self, client):
        with patch("api.main.query", return_value=MOCK_REVENUE):
            resp = client.get("/analytics/revenue-by-product")
        revenues = [r["total_revenue"] for r in resp.json()]
        assert revenues == sorted(revenues, reverse=True)

    def test_empty(self, client):
        with patch("api.main.query", return_value=[]):
            resp = client.get("/analytics/revenue-by-product")
        assert resp.json() == []


class TestMonthlyTrend:
    def test_returns_months(self, client):
        with patch("api.main.query", return_value=MOCK_TREND):
            resp = client.get("/analytics/monthly-trend")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert "month" in data[0]
        assert "revenue" in data[0]

    def test_revenue_is_numeric(self, client):
        with patch("api.main.query", return_value=MOCK_TREND):
            resp = client.get("/analytics/monthly-trend")
        for row in resp.json():
            assert isinstance(row["revenue"], (int, float))


class TestActiveAlerts:
    def test_returns_alerts(self, client):
        with patch("api.main.query", return_value=MOCK_ALERTS):
            resp = client.get("/analytics/alerts")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_alert_fields(self, client):
        with patch("api.main.query", return_value=MOCK_ALERTS):
            resp = client.get("/analytics/alerts")
        item = resp.json()[0]
        for field in ("sku", "name", "stock_qty", "reorder_level", "alert_type"):
            assert field in item

    def test_no_alerts(self, client):
        with patch("api.main.query", return_value=[]):
            resp = client.get("/analytics/alerts")
        assert resp.json() == []


class TestSlowMovers:
    def test_returns_list(self, client):
        with patch("api.main.query", return_value=MOCK_SLOW):
            resp = client.get("/analytics/slow-movers")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_has_sku_and_stock(self, client):
        with patch("api.main.query", return_value=MOCK_SLOW):
            resp = client.get("/analytics/slow-movers")
        item = resp.json()[0]
        assert "sku" in item
        assert "stock_qty" in item


class TestSupplierPerformance:
    def test_returns_suppliers(self, client):
        with patch("api.main.query", return_value=MOCK_SUPPLIERS):
            resp = client.get("/analytics/supplier-performance")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_supplier_fields(self, client):
        with patch("api.main.query", return_value=MOCK_SUPPLIERS):
            resp = client.get("/analytics/supplier-performance")
        item = resp.json()[0]
        assert "supplier" in item
        assert "inventory_value" in item
        assert "products_supplied" in item
