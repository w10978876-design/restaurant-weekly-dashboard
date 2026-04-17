from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd


def parse_business_date(value) -> date | None:
    if value is None or (isinstance(value, float) and str(value) == "nan"):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s or s in ("--", "合计", "nan"):
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).date()
        except ValueError:
            continue
    ts = pd.to_datetime(s, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_id_for_date(d: date) -> str:
    start = monday_of_week(d)
    return start.strftime("%Y-%m-%d")
