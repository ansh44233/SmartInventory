"""
SmartInventory — ML Demand Forecasting
=======================================
Trains a per-product linear regression on daily order history,
then forecasts demand for the next N days.

No heavy deps: numpy + scikit-learn only.

Usage (standalone):
    python ml/forecasting.py --product_id 1 --days 30

Imported by api/main.py for the /analytics/forecast/{product_id} endpoint.
"""

import os
import numpy as np
import psycopg2
import psycopg2.extras
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv
from sklearn.linear_model import Ridge
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import make_pipeline
from sklearn.metrics import mean_absolute_error

load_dotenv()
DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/smartinventory")


# ── Data classes ─────────────────────────────────────────────

@dataclass
class DailyDemand:
    date:     date
    quantity: int


@dataclass
class ForecastPoint:
    date:     str   # ISO format
    predicted_qty: float
    lower:    float   # 80% confidence lower bound
    upper:    float   # 80% confidence upper bound


@dataclass
class ForecastResult:
    product_id:   int
    product_name: str
    sku:          str
    history_days: int
    avg_daily_demand: float
    forecast:     list[ForecastPoint]
    restock_alert: Optional[str]   # warning if stock will run out
    model_mae:    float            # mean absolute error on training data


# ── DB helpers ───────────────────────────────────────────────

def _get_order_history(product_id: int) -> list[DailyDemand]:
    """
    Pull daily demand for a product from order_items.
    Only counts delivered/shipped/confirmed orders.
    """
    conn = psycopg2.connect(DSN)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT
            DATE(o.created_at)      AS order_date,
            SUM(oi.quantity)        AS total_qty
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE oi.product_id = %s
          AND o.status NOT IN ('cancelled', 'pending')
        GROUP BY DATE(o.created_at)
        ORDER BY DATE(o.created_at)
    """, (product_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [DailyDemand(date=r["order_date"], quantity=int(r["total_qty"])) for r in rows]


def _get_product_info(product_id: int) -> dict:
    conn = psycopg2.connect(DSN)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT id, sku, name, stock_qty, reorder_level FROM products WHERE id = %s",
        (product_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise ValueError(f"Product {product_id} not found")
    return dict(row)


# ── Feature engineering ──────────────────────────────────────

def _build_features(dates: list[date], quantities: list[int]):
    """
    Features per day:
      - day index (0, 1, 2, ...)
      - day of week (0=Mon … 6=Sun)  — captures weekly seasonality
      - 3-day rolling average
      - 7-day rolling average
    """
    n = len(dates)
    X = []
    y = quantities[:]

    for i, (d, q) in enumerate(zip(dates, quantities)):
        roll3 = np.mean(quantities[max(0, i-3):i]) if i > 0 else q
        roll7 = np.mean(quantities[max(0, i-7):i]) if i > 0 else q
        X.append([
            i,                  # trend
            d.weekday(),        # day-of-week seasonality
            roll3,              # short-term momentum
            roll7,              # medium-term momentum
        ])
    return np.array(X), np.array(y)


# ── Core forecast function ────────────────────────────────────

def forecast_product(
    product_id: int,
    horizon_days: int = 30,
) -> ForecastResult:
    """
    Train a polynomial Ridge regression on the product's order history
    and return a horizon_days forecast with confidence bounds.
    """
    info    = _get_product_info(product_id)
    history = _get_order_history(product_id)

    # ── Fill date gaps with 0 demand ────────────────────────
    if history:
        start = history[0].date
        end   = history[-1].date
        date_map = {h.date: h.quantity for h in history}
        all_dates = []
        all_qtys  = []
        cur_date  = start
        while cur_date <= end:
            all_dates.append(cur_date)
            all_qtys.append(date_map.get(cur_date, 0))
            cur_date += timedelta(days=1)
    else:
        # No history — return a zero forecast
        today = date.today()
        return ForecastResult(
            product_id=product_id,
            product_name=info["name"],
            sku=info["sku"],
            history_days=0,
            avg_daily_demand=0.0,
            forecast=[
                ForecastPoint(
                    date=str(today + timedelta(days=i+1)),
                    predicted_qty=0.0,
                    lower=0.0,
                    upper=0.0,
                )
                for i in range(horizon_days)
            ],
            restock_alert=None,
            model_mae=0.0,
        )

    avg_demand = float(np.mean(all_qtys)) if all_qtys else 0.0

    # ── Train model ─────────────────────────────────────────
    X_train, y_train = _build_features(all_dates, all_qtys)

    # Polynomial degree 2 Ridge — smooth trend without overfitting
    model = make_pipeline(PolynomialFeatures(degree=2), Ridge(alpha=1.0))
    model.fit(X_train, y_train)

    train_preds = model.predict(X_train)
    mae = float(mean_absolute_error(y_train, train_preds))

    # Residual std for confidence bounds (80% interval ~ ±1.28 std)
    residuals = y_train - train_preds
    std_err   = float(np.std(residuals))

    # ── Forecast ─────────────────────────────────────────────
    last_date = all_dates[-1]
    n_hist    = len(all_dates)
    forecast_points: list[ForecastPoint] = []
    rolling_window  = list(all_qtys[-7:])   # seed the rolling avg

    for i in range(1, horizon_days + 1):
        f_date  = last_date + timedelta(days=i)
        idx     = n_hist - 1 + i
        roll3   = float(np.mean(rolling_window[-3:])) if len(rolling_window) >= 3 else avg_demand
        roll7   = float(np.mean(rolling_window[-7:])) if len(rolling_window) >= 7 else avg_demand

        x_new   = np.array([[idx, f_date.weekday(), roll3, roll7]])
        pred    = float(model.predict(x_new)[0])
        pred    = max(0.0, pred)  # demand can't be negative

        lower   = max(0.0, pred - 1.28 * std_err)
        upper   = pred + 1.28 * std_err

        forecast_points.append(ForecastPoint(
            date=str(f_date),
            predicted_qty=round(pred, 2),
            lower=round(lower, 2),
            upper=round(upper, 2),
        ))
        rolling_window.append(pred)

    # ── Restock alert ─────────────────────────────────────────
    stock_qty     = int(info["stock_qty"])
    reorder_level = int(info["reorder_level"])
    cumulative    = 0.0
    restock_alert = None

    for fp in forecast_points:
        cumulative += fp.predicted_qty
        if cumulative >= stock_qty:
            days_until_stockout = forecast_points.index(fp) + 1
            restock_alert = (
                f"Stock ({stock_qty} units) projected to run out in "
                f"~{days_until_stockout} day(s) based on forecast demand."
            )
            break

    if restock_alert is None and stock_qty <= reorder_level:
        restock_alert = f"Stock ({stock_qty}) is already at or below reorder level ({reorder_level})."

    return ForecastResult(
        product_id=product_id,
        product_name=info["name"],
        sku=info["sku"],
        history_days=len(all_dates),
        avg_daily_demand=round(avg_demand, 2),
        forecast=forecast_points,
        restock_alert=restock_alert,
        model_mae=round(mae, 3),
    )


# ── Forecast all products ─────────────────────────────────────

def forecast_all(horizon_days: int = 30) -> list[dict]:
    """Return forecast summary for all products (top-level stats only)."""
    conn = psycopg2.connect(DSN)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM products ORDER BY id")
    ids = [r["id"] for r in cur.fetchall()]
    cur.close()
    conn.close()

    results = []
    for pid in ids:
        try:
            r = forecast_product(pid, horizon_days)
            total_forecast = sum(fp.predicted_qty for fp in r.forecast)
            results.append({
                "product_id":        r.product_id,
                "product_name":      r.product_name,
                "sku":               r.sku,
                "avg_daily_demand":  r.avg_daily_demand,
                "forecast_total_30d": round(total_forecast, 1),
                "restock_alert":     r.restock_alert,
                "model_mae":         r.model_mae,
            })
        except Exception as e:
            results.append({"product_id": pid, "error": str(e)})

    return results


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="SmartInventory demand forecast")
    parser.add_argument("--product_id", type=int, default=None)
    parser.add_argument("--days",       type=int, default=30)
    parser.add_argument("--all",        action="store_true")
    args = parser.parse_args()

    if args.all:
        data = forecast_all(args.days)
        print(json.dumps(data, indent=2))
    elif args.product_id:
        r = forecast_product(args.product_id, args.days)
        print(f"\n{'='*55}")
        print(f"  Forecast: {r.product_name} ({r.sku})")
        print(f"{'='*55}")
        print(f"  History:          {r.history_days} days")
        print(f"  Avg daily demand: {r.avg_daily_demand} units/day")
        print(f"  Model MAE:        {r.model_mae} units")
        if r.restock_alert:
            print(f"\n  ⚠️  {r.restock_alert}")
        print(f"\n  Next {args.days}-day forecast (first 7 shown):")
        print(f"  {'Date':<14} {'Predicted':>10} {'Low':>8} {'High':>8}")
        print(f"  {'-'*42}")
        for fp in r.forecast[:7]:
            print(f"  {fp.date:<14} {fp.predicted_qty:>10.1f} {fp.lower:>8.1f} {fp.upper:>8.1f}")
        print(f"  ... ({args.days - 7} more days)")
    else:
        parser.print_help()
