"""
Tests for ml/forecasting.py

All tests are pure unit tests — no database needed.
DB calls (_get_order_history, _get_product_info) are mocked throughout.

Run:
    pytest tests/test_forecasting.py -v
"""

import pytest
import numpy as np
from datetime import date, timedelta
from unittest.mock import patch

from ml.forecasting import (
    DailyDemand,
    ForecastPoint,
    ForecastResult,
    _build_features,
    forecast_product,
)


# ── Helpers ──────────────────────────────────────────────────

def make_history(n_days: int, qty: int = 3, start: date = None):
    """Return n_days of consecutive DailyDemand with constant quantity."""
    if start is None:
        start = date(2026, 9, 1)
    return [
        DailyDemand(date=start + timedelta(days=i), quantity=qty)
        for i in range(n_days)
    ]


def make_product(stock_qty: int = 100, reorder_level: int = 10) -> dict:
    return {
        "id": 1,
        "sku": "TST-001",
        "name": "Test Product",
        "stock_qty": stock_qty,
        "reorder_level": reorder_level,
    }


# ── Feature engineering ───────────────────────────────────────

class TestBuildFeatures:
    def test_output_shape(self):
        dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(10)]
        qtys  = [2] * 10
        X, y  = _build_features(dates, qtys)
        assert X.shape == (10, 4)
        assert len(y) == 10

    def test_day_index_increases(self):
        dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(5)]
        qtys  = [1] * 5
        X, _  = _build_features(dates, qtys)
        indices = X[:, 0].tolist()
        assert indices == sorted(indices)
        assert indices[0] == 0

    def test_weekday_in_range(self):
        dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(14)]
        qtys  = [1] * 14
        X, _  = _build_features(dates, qtys)
        weekdays = X[:, 1]
        assert all(0 <= d <= 6 for d in weekdays)

    def test_rolling_avg_first_row_uses_own_value(self):
        """At index 0, there is no prior data — rolling avgs should equal the first qty."""
        dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(5)]
        qtys  = [5, 3, 3, 3, 3]
        X, _  = _build_features(dates, qtys)
        # First row: roll3 and roll7 columns should equal qtys[0]
        assert X[0, 2] == 5   # roll3
        assert X[0, 3] == 5   # roll7

    def test_labels_match_input_quantities(self):
        dates = [date(2026, 6, 1) + timedelta(days=i) for i in range(7)]
        qtys  = [1, 2, 3, 4, 5, 6, 7]
        _, y  = _build_features(dates, qtys)
        assert list(y) == qtys

    def test_single_day(self):
        X, y = _build_features([date(2026, 1, 1)], [4])
        assert X.shape == (1, 4)
        assert y[0] == 4


# ── forecast_product — no history ────────────────────────────

class TestForecastNoHistory:
    def test_zero_forecast_returned(self):
        with patch("ml.forecasting._get_product_info", return_value=make_product()), \
             patch("ml.forecasting._get_order_history", return_value=[]):
            result = forecast_product(1, horizon_days=10)

        assert result.history_days == 0
        assert result.avg_daily_demand == 0.0
        assert len(result.forecast) == 10
        for fp in result.forecast:
            assert fp.predicted_qty == 0.0
            assert fp.lower == 0.0
            assert fp.upper == 0.0

    def test_no_restock_alert_on_zero_history_ok_stock(self):
        with patch("ml.forecasting._get_product_info", return_value=make_product(stock_qty=50, reorder_level=10)), \
             patch("ml.forecasting._get_order_history", return_value=[]):
            result = forecast_product(1)
        assert result.restock_alert is None

    def test_forecast_dates_are_in_future(self):
        with patch("ml.forecasting._get_product_info", return_value=make_product()), \
             patch("ml.forecasting._get_order_history", return_value=[]):
            result = forecast_product(1, horizon_days=5)
        today = date.today()
        for fp in result.forecast:
            assert date.fromisoformat(fp.date) > today


# ── forecast_product — with history ──────────────────────────

class TestForecastWithHistory:
    def _run(self, n_days=30, qty=3, stock=100, reorder=10, horizon=14):
        history = make_history(n_days, qty=qty)
        with patch("ml.forecasting._get_product_info", return_value=make_product(stock, reorder)), \
             patch("ml.forecasting._get_order_history", return_value=history):
            return forecast_product(1, horizon_days=horizon)

    def test_returns_correct_horizon(self):
        result = self._run(horizon=14)
        assert len(result.forecast) == 14

    def test_forecast_dates_are_consecutive(self):
        result = self._run(horizon=7)
        dates = [date.fromisoformat(fp.date) for fp in result.forecast]
        for i in range(1, len(dates)):
            assert dates[i] == dates[i-1] + timedelta(days=1)

    def test_predicted_qty_is_non_negative(self):
        result = self._run()
        for fp in result.forecast:
            assert fp.predicted_qty >= 0.0

    def test_lower_bound_lte_predicted(self):
        result = self._run()
        for fp in result.forecast:
            assert fp.lower <= fp.predicted_qty + 1e-6

    def test_upper_bound_gte_predicted(self):
        result = self._run()
        for fp in result.forecast:
            assert fp.upper >= fp.predicted_qty - 1e-6

    def test_lower_bound_non_negative(self):
        result = self._run()
        for fp in result.forecast:
            assert fp.lower >= 0.0

    def test_history_days_correct(self):
        result = self._run(n_days=20)
        assert result.history_days == 20

    def test_avg_daily_demand_positive(self):
        result = self._run(n_days=30, qty=5)
        assert result.avg_daily_demand > 0.0

    def test_model_mae_non_negative(self):
        result = self._run()
        assert result.model_mae >= 0.0

    def test_product_name_and_sku_propagated(self):
        result = self._run()
        assert result.product_name == "Test Product"
        assert result.sku == "TST-001"


# ── Date gap filling ─────────────────────────────────────────

class TestDateGapFilling:
    def test_gaps_filled_as_zero(self):
        """History with a 2-day gap should produce a contiguous range."""
        start = date(2026, 10, 1)
        history = [
            DailyDemand(date=start,                quantity=5),
            DailyDemand(date=start+timedelta(days=3), quantity=4),  # gap: days 1,2
        ]
        with patch("ml.forecasting._get_product_info", return_value=make_product()), \
             patch("ml.forecasting._get_order_history", return_value=history):
            result = forecast_product(1, horizon_days=5)

        # 4 days in range (days 0–3) → history_days=4
        assert result.history_days == 4

    def test_single_day_history(self):
        history = [DailyDemand(date=date(2026, 10, 1), quantity=3)]
        with patch("ml.forecasting._get_product_info", return_value=make_product()), \
             patch("ml.forecasting._get_order_history", return_value=history):
            result = forecast_product(1, horizon_days=7)
        assert len(result.forecast) == 7
        assert result.history_days == 1


# ── Restock alert logic ───────────────────────────────────────

class TestRestockAlert:
    def test_alert_fires_when_stock_runs_out(self):
        """With stock=5 and avg demand ~3/day, should alert within a few days."""
        history = make_history(30, qty=3)
        with patch("ml.forecasting._get_product_info",
                   return_value=make_product(stock_qty=5, reorder_level=2)), \
             patch("ml.forecasting._get_order_history", return_value=history):
            result = forecast_product(1, horizon_days=30)
        assert result.restock_alert is not None
        assert "run out" in result.restock_alert.lower()

    def test_no_alert_when_stock_is_ample(self):
        """Stock=10000 with low demand should not trigger an alert."""
        history = make_history(30, qty=1)
        with patch("ml.forecasting._get_product_info",
                   return_value=make_product(stock_qty=10000, reorder_level=10)), \
             patch("ml.forecasting._get_order_history", return_value=history):
            result = forecast_product(1, horizon_days=30)
        assert result.restock_alert is None

    def test_already_below_reorder_level(self):
        """Stock already below reorder_level → alert even with no stockout in forecast."""
        history = make_history(30, qty=1)
        with patch("ml.forecasting._get_product_info",
                   return_value=make_product(stock_qty=5, reorder_level=10)), \
             patch("ml.forecasting._get_order_history", return_value=history):
            result = forecast_product(1, horizon_days=30)
        # Either a stockout alert or an "already below reorder" alert
        assert result.restock_alert is not None

    def test_alert_contains_stock_qty(self):
        history = make_history(30, qty=5)
        with patch("ml.forecasting._get_product_info",
                   return_value=make_product(stock_qty=8, reorder_level=2)), \
             patch("ml.forecasting._get_order_history", return_value=history):
            result = forecast_product(1, horizon_days=30)
        if result.restock_alert:
            assert "8" in result.restock_alert


# ── API endpoint tests ────────────────────────────────────────

class TestForecastAPI:
    def test_forecast_endpoint_success(self, client):
        history = make_history(20, qty=2)
        with patch("ml.forecasting._get_product_info", return_value=make_product()), \
             patch("ml.forecasting._get_order_history", return_value=history):
            resp = client.get("/analytics/forecast/1?days=7")
        assert resp.status_code == 200
        body = resp.json()
        assert "forecast" in body
        assert len(body["forecast"]) == 7
        assert "product_name" in body
        assert "model_mae" in body

    def test_forecast_endpoint_404(self, client):
        with patch("ml.forecasting._get_product_info",
                   side_effect=ValueError("Product 9999 not found")):
            resp = client.get("/analytics/forecast/9999")
        assert resp.status_code == 404

    def test_forecast_days_param(self, client):
        history = make_history(20, qty=2)
        with patch("ml.forecasting._get_product_info", return_value=make_product()), \
             patch("ml.forecasting._get_order_history", return_value=history):
            resp = client.get("/analytics/forecast/1?days=14")
        assert len(resp.json()["forecast"]) == 14

    def test_forecast_all_endpoint(self, client):
        history = make_history(20, qty=2)
        with patch("ml.forecasting._get_product_info", return_value=make_product()), \
             patch("ml.forecasting._get_order_history", return_value=history), \
             patch("api.main.forecast_all", return_value=[{
                 "product_id": 1, "product_name": "Test", "sku": "TST-001",
                 "avg_daily_demand": 2.0, "forecast_total_30d": 60.0,
                 "restock_alert": None, "model_mae": 0.5
             }]):
            resp = client.get("/analytics/forecast")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
