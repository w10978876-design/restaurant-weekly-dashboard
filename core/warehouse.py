from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_weekly_metrics_json(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(
            columns=[
                "store_id",
                "week_id",
                "revenue",
                "orders",
                "table_turnover_rate",
                "avg_order_value",
                "discount_amount",
                "groupbuy_count",
                "groupbuy_income",
                "review_score",
                "repurchase_rate",
                "repeat_payers",
                "total_payers",
                "waste_amount",
                "updated_at",
            ]
        )
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    rows = payload.get("rows", [])
    if not rows:
        return pd.DataFrame(
            columns=[
                "store_id",
                "week_id",
                "revenue",
                "orders",
                "table_turnover_rate",
                "avg_order_value",
                "discount_amount",
                "groupbuy_count",
                "groupbuy_income",
                "review_score",
                "repurchase_rate",
                "repeat_payers",
                "total_payers",
                "waste_amount",
                "updated_at",
            ]
        )
    return pd.DataFrame(rows)


def save_weekly_metrics_json(path: str, df: pd.DataFrame) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = df.to_dict(orient="records")
    payload = {"version": 1, "saved_at": _utc_now_iso(), "rows": rows}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def merge_weekly_history(history: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        base = fresh.copy()
    elif fresh.empty:
        base = history.copy()
    else:
        base = pd.concat([history, fresh], ignore_index=True)
    if base.empty:
        return base
    base = base.sort_values(["store_id", "week_id", "updated_at"])
    base = base.drop_duplicates(subset=["store_id", "week_id"], keep="last")
    return base.reset_index(drop=True)


def try_save(path: str, df: pd.DataFrame) -> tuple[bool, str]:
    try:
        save_weekly_metrics_json(path, df)
        return True, ""
    except Exception as exc:
        return False, str(exc)
