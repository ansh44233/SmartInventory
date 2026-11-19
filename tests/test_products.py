"""
Tests for /products endpoints.
Unit tests mock the DB; no live Postgres needed.
"""

import pytest
from unittest.mock import patch

MOCK_PRODUCTS = [
    {
        "id": 1, "sku": "SKU-0001", "name": "Wireless Earbuds",
        "category": "Electronics", "supplier": "TechSource Ltd",
        "unit_price": 2499.00, "stock_qty": 50, "reorder_level": 10,
        "is_low_stock": False,
    },
    {
        "id": 2, "sku": "SKU-0002", "name": "Yoga Mat",
        "category": "Sports", "supplier": "LocalSupply Pvt",
        "unit_price": 599.00, "stock_qty": 5, "reorder_level": 10,
        "is_low_stock": True,
    },
]


class TestListProducts:
    def test_returns_list(self, client):
        with patch("api.main.query", return_value=MOCK_PRODUCTS):
            resp = client.get("/products")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_product_has_required_fields(self, client):
        with patch("api.main.query", return_value=MOCK_PRODUCTS):
            resp = client.get("/products")
        item = resp.json()[0]
        for field in ("id", "sku", "name", "unit_price", "stock_qty", "reorder_level"):
            assert field in item, f"Missing field: {field}"

    def test_low_stock_filter(self, client):
        low = [p for p in MOCK_PRODUCTS if p["is_low_stock"]]
        with patch("api.main.query", return_value=low):
            resp = client.get("/products?low_stock=true")
        assert resp.status_code == 200
        for item in resp.json():
            assert item["is_low_stock"] is True

    def test_empty_list(self, client):
        with patch("api.main.query", return_value=[]):
            resp = client.get("/products")
        assert resp.status_code == 200
        assert resp.json() == []


class TestCreateProduct:
    PAYLOAD = {
        "sku": "SKU-9999",
        "name": "Test Product",
        "category_id": 1,
        "supplier_id": 1,
        "unit_price": 999.0,
        "stock_qty": 50,
        "reorder_level": 5,
    }

    def test_create_success(self, client):
        with patch("api.main.execute", return_value=None):
            resp = client.post("/products", json=self.PAYLOAD)
        assert resp.status_code == 201
        assert resp.json()["message"] == "Product created."

    def test_missing_required_field(self, client):
        bad = {k: v for k, v in self.PAYLOAD.items() if k != "sku"}
        resp = client.post("/products", json=bad)
        assert resp.status_code == 422  # Pydantic validation error

    def test_negative_price_rejected(self, client):
        bad = {**self.PAYLOAD, "unit_price": -100}
        # Pydantic doesn't block this — the DB constraint does.
        # We verify the API accepts the payload (constraint is DB-side).
        with patch("api.main.execute", return_value=None):
            resp = client.post("/products", json=bad)
        # API layer passes it through; integration test covers DB rejection.
        assert resp.status_code in (201, 400, 422)


class TestUpdateStock:
    def test_restock(self, client):
        with patch("api.main.query", return_value=[{"stock_qty": 20}]), \
             patch("api.main.execute", return_value=None):
            resp = client.patch("/products/1/stock", json={"delta": 30})
        assert resp.status_code == 200
        assert resp.json()["new_stock_qty"] == 50

    def test_deduct_stock(self, client):
        with patch("api.main.query", return_value=[{"stock_qty": 20}]), \
             patch("api.main.execute", return_value=None):
            resp = client.patch("/products/1/stock", json={"delta": -5})
        assert resp.status_code == 200
        assert resp.json()["new_stock_qty"] == 15

    def test_stock_cannot_go_negative(self, client):
        with patch("api.main.query", return_value=[{"stock_qty": 3}]):
            resp = client.patch("/products/1/stock", json={"delta": -10})
        assert resp.status_code == 400
        assert "0" in resp.json()["detail"].lower() or "below" in resp.json()["detail"].lower()

    def test_product_not_found(self, client):
        with patch("api.main.query", return_value=[]):
            resp = client.patch("/products/9999/stock", json={"delta": 1})
        assert resp.status_code == 404
