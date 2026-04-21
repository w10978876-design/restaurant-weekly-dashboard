from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import pandas as pd

from core.paths import data_dir, weekly_metrics_path
from core.warehouse import load_weekly_metrics_json, merge_weekly_history, try_save
from ingestion.pipeline import StoreBundle, load_all_stores
from ingestion.excel_reader import to_number


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _table_key_row(row: pd.Series) -> str:
    z = str(row.get("桌牌号", "")).strip()
    if z and z not in ("--", "nan", "None"):
        return z
    return str(row.get("取餐号", "")).strip()


def _repurchase_for_week(payments: pd.DataFrame | None, week_id: str) -> tuple[float | None, int, int]:
    """支付明细：同一付款人信息当周不重复业务单号>1 视为复购用户。返回 (复购率%, 复购人数, 付款人数)。"""
    if payments is None or payments.empty or "week_id" not in payments.columns:
        return None, 0, 0
    sub = payments[payments["week_id"].astype(str) == str(week_id)]
    if sub.empty:
        return None, 0, 0
    if "_payer" not in sub.columns:
        return None, 0, 0
    p = sub.copy()
    p["_payer"] = p["_payer"].astype(str).str.strip()
    p = p[(p["_payer"] != "") & (~p["_payer"].str.lower().isin(["nan", "none"]))]
    if p.empty:
        return 0.0, 0, 0
    if "业务单号" in p.columns:
        vc = p.groupby("_payer", dropna=True)["业务单号"].nunique()
    else:
        vc = p.groupby("_payer", dropna=True).size()
    tot = int((vc > 0).sum())
    rep = int((vc > 1).sum())
    if tot == 0:
        return None, 0, 0
    rate = round(float(rep / tot) * 100.0, 2)
    return rate, rep, tot


def _rating_last_actual_for_week(store_rating: pd.DataFrame | None, week_id: str) -> float:
    if store_rating is None or store_rating.empty:
        return float("nan")
    sub = store_rating[store_rating["week_id"].astype(str) == str(week_id)]
    if sub.empty:
        return float("nan")
    sub = sub.sort_values("_ts")
    v = sub.iloc[-1]["实际值"]
    if pd.isna(v):
        return float("nan")
    return float(v)


def _rating_nearest_actual_for_week(store_rating: pd.DataFrame | None, week_id: str) -> float:
    """当周无数据时，取距离该周最近日期的「实际值」(绝对天数最近)。"""
    if store_rating is None or store_rating.empty:
        return float("nan")
    try:
        wk_start = datetime.strptime(str(week_id), "%Y-%m-%d").date()
    except Exception:
        return float("nan")
    target = pd.Timestamp(wk_start + timedelta(days=3))
    s = store_rating.copy()
    s = s[s["_ts"].notna() & s["实际值"].notna()].copy()
    if s.empty:
        return float("nan")
    s["_delta"] = (s["_ts"] - target).abs()
    s = s.sort_values(["_delta", "_ts"])
    v = s.iloc[0]["实际值"]
    return float(v) if pd.notna(v) else float("nan")


def compute_fresh_weekly_table(bundle: StoreBundle, store_id: str) -> pd.DataFrame:
    o = bundle.orders
    if o is None or o.empty:
        return pd.DataFrame()

    df = o.copy()
    if "订单状态" in df.columns:
        df = df[df["订单状态"].astype(str) == "已结账"]
    df = df[df["week_id"].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    df["table_key"] = df.apply(_table_key_row, axis=1)

    disc_map = pd.Series(dtype=float)
    if bundle.discounts is not None and not bundle.discounts.empty and "订单编号" in bundle.discounts.columns:
        d0 = bundle.discounts.copy()
        if "discount_amount" not in d0.columns and "折扣优惠金额（元）" in d0.columns:
            d0["discount_amount"] = to_number(d0["折扣优惠金额（元）"])
        owk = bundle.orders[["订单号", "week_id"]].drop_duplicates().copy()
        owk["订单号"] = owk["订单号"].astype(str)
        d0 = d0.copy()
        d0["订单编号"] = d0["订单编号"].astype(str)
        m = d0.merge(owk, left_on="订单编号", right_on="订单号", how="left")
        disc_map = m.groupby("week_id")["discount_amount"].sum(min_count=1)

    gb_count = pd.Series(dtype=float)
    gb_income = pd.Series(dtype=float)
    if bundle.groupbuy is not None and not bundle.groupbuy.empty:
        g0 = bundle.groupbuy.copy()
        g0 = g0[g0["week_id"].notna()]
        if "商家预计应得(元)" in g0.columns:
            g0["gb_income"] = to_number(g0["商家预计应得(元)"])
            gb_income = g0.groupby("week_id")["gb_income"].sum(min_count=1)
        gb_count = g0.groupby("week_id").size()

    # 门店评分：优先「门店评分」sheet「实际值」当周按时间最后一条；否则回退为评价明细总分周均
    srs = bundle.store_rating_sheet
    rev_map_mean = pd.Series(dtype=float)
    if bundle.reviews is not None and not bundle.reviews.empty:
        r0 = bundle.reviews.copy()
        r0 = r0[r0["week_id"].notna()]
        if "评价状态" in r0.columns:
            r0 = r0[r0["评价状态"].astype(str) == "正常"]
        if "score" in r0.columns:
            rev_map_mean = r0.groupby("week_id")["score"].mean()

    waste_total = 0.0
    if bundle.waste is not None and not bundle.waste.empty and "waste_amount" in bundle.waste.columns:
        waste_total = float(bundle.waste["waste_amount"].fillna(0).sum())

    rows: list[dict] = []
    weeks = sorted(df["week_id"].dropna().unique().tolist())
    rev_by_week = df.groupby("week_id")["order_revenue"].sum()
    for wk in weeks:
        g = df[df["week_id"] == wk]
        revenue = float(g["order_revenue"].fillna(0).sum())
        orders = int(g["订单号"].nunique())
        aov = float(revenue / orders) if orders else 0.0

        slots = int(g.groupby("business_date")["table_key"].nunique().sum())
        turnover = float(orders / max(slots, 1))

        discount_amount = float(disc_map.get(wk, 0.0) or 0.0)
        groupbuy_count = int(gb_count.get(wk, 0) or 0)
        groupbuy_income = float(gb_income.get(wk, 0.0) or 0.0)
        if srs is not None and not srs.empty:
            review_score = _rating_last_actual_for_week(srs, str(wk))
            if pd.isna(review_score):
                review_score = _rating_nearest_actual_for_week(srs, str(wk))
                if pd.isna(review_score):
                    review_score = float(rev_map_mean.loc[wk]) if wk in rev_map_mean.index else float("nan")
        else:
            review_score = float(rev_map_mean.loc[wk]) if wk in rev_map_mean.index else float("nan")

        rp_rate, rp_rep, rp_tot = _repurchase_for_week(bundle.payments, str(wk))

        rows.append(
            {
                "store_id": store_id,
                "week_id": wk,
                "revenue": revenue,
                "orders": orders,
                "table_turnover_rate": turnover,
                "avg_order_value": aov,
                "discount_amount": discount_amount,
                "groupbuy_count": groupbuy_count,
                "groupbuy_income": groupbuy_income,
                "review_score": review_score,
                "repurchase_rate": float("nan") if rp_rate is None else float(rp_rate),
                "repeat_payers": int(rp_rep),
                "total_payers": int(rp_tot),
                "waste_amount": 0.0,
                "updated_at": _utc_now_iso(),
            }
        )

    out = pd.DataFrame(rows)
    if waste_total > 0 and not out.empty:
        rev_sum = float(out["revenue"].sum()) or 1.0
        out["waste_amount"] = out["revenue"].astype(float) / rev_sum * waste_total

    return out


@dataclass
class StoreInfo:
    store_id: str
    display_name: str


class MetricsEngine:
    """
    Loads Excel exports under data/<门店>/, merges historical weekly KPI JSON,
    and exposes precomputed weekly metrics for Streamlit.
    """

    def __init__(self, auto_persist: bool = True):
        self._root = data_dir()
        self._warehouse_path = weekly_metrics_path()
        self._auto_persist = auto_persist
        self._bundles: dict[str, StoreBundle] = load_all_stores(self._root)
        self._history = load_weekly_metrics_json(self._warehouse_path)
        self._fresh_parts: list[pd.DataFrame] = []
        for store_id, bundle in self._bundles.items():
            self._fresh_parts.append(compute_fresh_weekly_table(bundle, store_id))
        self._fresh = pd.concat(self._fresh_parts, ignore_index=True) if self._fresh_parts else pd.DataFrame()
        self._merged = merge_weekly_history(self._history, self._fresh)

        if self._auto_persist and not self._merged.empty:
            ok, err = try_save(self._warehouse_path, self._merged)
            self._last_persist_ok = ok
            self._last_persist_error = err
        else:
            self._last_persist_ok = True
            self._last_persist_error = ""

    def persist_status(self) -> tuple[bool, str]:
        return self._last_persist_ok, self._last_persist_error

    def list_stores(self) -> list[StoreInfo]:
        return [StoreInfo(store_id=k, display_name=k) for k in sorted(self._bundles.keys())]

    def resolved_files(self, store_id: str) -> dict[str, str | None]:
        b = self._bundles.get(store_id)
        if not b:
            return {}
        return dict(b.resolved_paths)

    def get_store_bundle(self, store_id: str) -> StoreBundle | None:
        return self._bundles.get(store_id)

    def get_available_weeks(self, store_id: str) -> list[str]:
        sub = self._merged[self._merged["store_id"] == store_id]
        if sub.empty:
            return []
        weeks = sorted(sub["week_id"].dropna().unique().tolist())
        return weeks

    def get_trend_data(self, store_id: str) -> pd.DataFrame:
        sub = self._merged[self._merged["store_id"] == store_id].copy()
        if sub.empty:
            return sub
        sub = sub.sort_values("week_id")
        return sub.reset_index(drop=True)

    def get_metrics_for_week(self, store_id: str, week_id: str) -> dict:
        sub = self._merged[self._merged["store_id"] == store_id].sort_values("week_id")
        row = sub[sub["week_id"] == week_id]
        if row.empty:
            nan = float("nan")
            cur = {
                "week_id": week_id,
                "revenue": 0.0,
                "orders": 0,
                "table_turnover_rate": 0.0,
                "avg_order_value": 0.0,
                "discount_amount": 0.0,
                "groupbuy_count": 0,
                "groupbuy_income": 0.0,
                "review_score": nan,
                "repurchase_rate": nan,
                "repeat_payers": 0,
                "total_payers": 0,
                "waste_amount": 0.0,
            }
            wow = {k: 0.0 for k in ["revenue", "orders", "table_turnover_rate", "avg_order_value"]}
            return {"current": cur, "wow": wow}

        cur = row.iloc[-1].to_dict()
        wow = {k: 0.0 for k in ["revenue", "orders", "table_turnover_rate", "avg_order_value"]}
        prev_rows = sub[sub["week_id"] < week_id]
        if not prev_rows.empty:
            prev = prev_rows.iloc[-1]
            for key in ["revenue", "orders", "table_turnover_rate", "avg_order_value"]:
                pv = float(prev.get(key, 0.0) or 0.0)
                cv = float(cur.get(key, 0.0) or 0.0)
                if pv == 0:
                    wow[key] = 0.0 if cv == 0 else 100.0
                else:
                    wow[key] = round((cv - pv) / pv * 100.0, 2)

        return {"current": cur, "wow": wow}

    def read_weather_markdown(self) -> str | None:
        from core.paths import weather_md_path
        import os

        p = weather_md_path()
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
