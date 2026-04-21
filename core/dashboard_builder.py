"""
Build full dashboard JSON from Excel multi-sheet bundles (BUSINESS_LOGIC_SPEC.md).
Writes data/warehouse/ui_payload.json for the Node UI.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from data_processor import generate_summary
from core.metrics_engine import MetricsEngine, _repurchase_for_week
from core.paths import data_dir, ui_payload_path
from core.review_nlp import extract_keywords_with_meta
from core.status_rules import aov_status, orders_status, retention_status, revenue_status
from core.weeks import parse_business_date, week_id_for_date
from core.weather_md import is_abnormal_weather, is_normal_weather, load_weather_map
from ingestion.category_mapping import normalize_join_key
from ingestion.excel_reader import to_number
from ingestion.pipeline import StoreBundle, load_all_stores

TOTAL_TABLES = 50

PERIOD_DEF = [
    ("上午 (08:00-10:30)", 8.0, 10.5),
    ("午餐 (10:30-14:00)", 10.5, 14.0),
    ("下午茶 (14:00-17:00)", 14.0, 17.0),
    ("晚餐 (17:00-21:00)", 17.0, 21.0),
]

SLOT_LABELS = {p[0] for p in PERIOD_DEF}


def _normalize_dish_key(s: str) -> str:
    """与 ingestion.category_mapping.normalize_join_key 一致，便于名称/大类与映射表 join。"""
    return normalize_join_key(s)


def _wow(cur: float, prev: float) -> float:
    if not prev:
        return 100.0 if cur else 0.0
    return round((cur - prev) / prev * 100.0, 2)


def _parse_week_range(week_id: str) -> str:
    start = datetime.strptime(week_id, "%Y-%m-%d").date()
    end = start + timedelta(days=6)
    return f"{start.isoformat()} ~ {end.isoformat()}"


def _order_time_column(df: pd.DataFrame) -> str | None:
    for c in ("开桌时间", "下单时间", "结账时间", "营业开始时间", "订单时间", "创建时间"):
        if c in df.columns:
            return c
    return None


def _review_text_column(df: pd.DataFrame) -> str | None:
    for c in ("评价内容", "文字评价", "评价详情", "内容", "评论内容", "用户评价", "反馈内容"):
        if c in df.columns:
            return c
    return None


def _weather_icon_type(desc: str) -> str:
    d = desc or ""
    if any(x in d for x in ("雨", "雪", "雷", "阵雨", "雷阵雨")):
        return "雨雪"
    if "沙" in d or "尘" in d:
        return "沙尘"
    if "大风" in d or "阵风" in d:
        return "大风"
    if "晴" in d and "雨" not in d:
        return "晴"
    return "阴"


def _slot_for_ts(ts: datetime) -> str | None:
    if pd.isna(ts):
        return None
    h = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
    for label, lo, hi in PERIOD_DEF:
        if label.startswith("晚餐"):
            if lo <= h <= hi + 1e-6:
                return label
        elif lo <= h < hi:
            return label
    return None


def _prep_orders(bundle: StoreBundle) -> pd.DataFrame | None:
    o = bundle.orders
    if o is None or o.empty:
        return None
    df = o.copy()
    if "订单状态" in df.columns:
        df = df[df["订单状态"].astype(str) == "已结账"]
    if "week_id" not in df.columns and "营业日期" in df.columns:
        df["business_date"] = df["营业日期"].map(parse_business_date)
        df["week_id"] = df["business_date"].map(lambda d: week_id_for_date(d) if d else None)
    tc = _order_time_column(df)
    if tc:
        df["_ts"] = pd.to_datetime(df[tc], errors="coerce")
        df["_slot"] = df["_ts"].map(_slot_for_ts)
    else:
        df["_slot"] = None
    if "order_revenue" not in df.columns:
        if "订单收入（元）" in df.columns:
            df["order_revenue"] = to_number(df["订单收入（元）"])
        elif "支付合计（元）" in df.columns:
            df["order_revenue"] = to_number(df["支付合计（元）"])
        else:
            df["order_revenue"] = 0.0
    return df


def _returns_count_week(bundle: StoreBundle, week_id: str) -> tuple[int, int]:
    ret = bundle.sales_return
    if ret is None or ret.empty:
        return 0, 0
    r = ret.copy()
    if "week_id" not in r.columns and "营业日期" in r.columns:
        r["business_date"] = r["营业日期"].map(parse_business_date)
        r["week_id"] = r["business_date"].map(lambda d: week_id_for_date(d) if d else None)
    cur = len(r[r["week_id"] == week_id])
    weeks = sorted(r["week_id"].dropna().unique().tolist())
    prev_w = None
    for w in weeks:
        if w < week_id:
            prev_w = w
    prev = len(r[r["week_id"] == prev_w]) if prev_w else 0
    return cur, prev


def _waste_week(bundle: StoreBundle, week_id: str, week_revenue: float, total_rev_all_weeks: float) -> float:
    w = bundle.waste
    if w is None or w.empty or "waste_amount" not in w.columns:
        return 0.0
    w = w.copy()
    date_col = None
    for c in ("报损日期", "营业日期", "日期"):
        if c in w.columns:
            date_col = c
            break
    if date_col:
        w["business_date"] = w[date_col].map(parse_business_date)
        w["week_id"] = w["business_date"].map(lambda d: week_id_for_date(d) if d else None)
        sub = w[w["week_id"] == week_id]
        return float(sub["waste_amount"].fillna(0).sum()) if not sub.empty else 0.0
    tot = float(w["waste_amount"].fillna(0).sum())
    if total_rev_all_weeks <= 0:
        return 0.0
    return tot * (week_revenue / total_rev_all_weeks)


def _menu_as_category_map(menu: pd.DataFrame | None) -> pd.DataFrame | None:
    if menu is None or menu.empty:
        return None
    dish_c = cat_c = None
    for c in menu.columns:
        t = str(c).strip()
        if t in ("菜品名称", "商品名称", "品名"):
            dish_c = c
            break
    for c in menu.columns:
        t = str(c).strip()
        if t in ("品类", "分类", "类别", "系列", "档口"):
            cat_c = c
            break
    if not dish_c or not cat_c or dish_c == cat_c:
        return None
    out = menu[[dish_c, cat_c]].copy()
    out.columns = ["菜品名称", "品类"]
    out["菜品名称"] = out["菜品名称"].map(_normalize_dish_key)
    out["品类"] = out["品类"].astype(str).str.strip()
    out = out[(out["菜品名称"] != "") & (out["菜品名称"].str.lower() != "nan")]
    out = out.drop_duplicates(subset=["菜品名称"], keep="last")
    return out if not out.empty else None


def _resolve_category_lookup(bundle: StoreBundle) -> pd.DataFrame | None:
    if bundle.category_map is not None and not bundle.category_map.empty:
        cm = bundle.category_map.copy()
        if "菜品名称" in cm.columns and "品类" in cm.columns:
            cm["菜品名称"] = cm["菜品名称"].map(_normalize_dish_key)
            cm["品类"] = cm["品类"].astype(str).str.strip()
            return cm
    return _menu_as_category_map(bundle.menu)


def _sales_major_class_column(s: pd.DataFrame) -> str | None:
    """
    销售明细中用于 join 映射表的主键列：与用户表一致为「大类名称」；
    兼容「大类」「菜品大类」及「xx大类名称」等（表头按 strip 后匹配）。
    """
    candidates = ("大类名称", "大类", "菜品大类", "商品大类")
    by_strip = {str(c).strip(): c for c in s.columns}
    for name in candidates:
        if name in by_strip:
            return by_strip[name]
    for c in s.columns:
        st = str(c).strip()
        if st.endswith("大类名称") or st.endswith("大类名"):
            return c
    return None


def _category_frame(bundle: StoreBundle, week_id: str) -> pd.DataFrame:
    """
    二、品类：销售明细有菜品名称 + 大类名称（主键）→ 用品类映射表把【类目】挂到明细上 → 仅按【类目】汇总。
    页面只展示类目维度；「覆盖大类数」= 归入该类目的不重复大类名称条数（不展示具体大类名）。
    未命中映射的归为「未映射类目」。
    """
    sold = bundle.sales_sold
    if sold is None or sold.empty:
        return pd.DataFrame()
    s = sold.copy()
    if "week_id" not in s.columns and "营业日期" in s.columns:
        s["business_date"] = s["营业日期"].map(parse_business_date)
        s["week_id"] = s["business_date"].map(lambda d: week_id_for_date(d) if d else None)
    s = s[s["week_id"] == week_id]
    class_col = _sales_major_class_column(s)
    if not class_col:
        return pd.DataFrame()

    s["qty"] = to_number(s["销售数量"]) if "销售数量" in s.columns else 1
    s["rev"] = to_number(s["菜品收入（元）"]) if "菜品收入（元）" in s.columns else 0
    for drop_c in ("品类", "类目"):
        if drop_c in s.columns:
            s = s.drop(columns=[drop_c], errors="ignore")

    m = s.copy()
    m["_major_raw"] = m[class_col].astype(str).str.strip()
    m = m[(m["_major_raw"] != "") & (m["_major_raw"].str.lower() != "nan")]
    if m.empty:
        return pd.DataFrame()
    m["_cls_join"] = m["_major_raw"].map(_normalize_dish_key)

    UNMAPPED = "未映射类目"
    cm_cls = bundle.category_class_map
    if cm_cls is not None and not cm_cls.empty and "类目" in cm_cls.columns:
        cm = cm_cls.copy()
        cm["_cls_join"] = cm["菜品大类"].map(_normalize_dish_key)
        m = m.merge(cm.drop(columns=["菜品大类"]), on="_cls_join", how="left")
        m["类目"] = m["类目"].fillna(UNMAPPED)
    else:
        m["类目"] = UNMAPPED
    m = m.drop(columns=["_cls_join"], errors="ignore")

    g = (
        m.groupby("类目", dropna=False)
        .agg(qty=("qty", "sum"), rev=("rev", "sum"), coveredMajorClassCount=("_major_raw", pd.Series.nunique))
        .reset_index()
    )
    return g.rename(columns={"类目": "name"})


def _menu_dish_names(menu: pd.DataFrame | None) -> list[str]:
    if menu is None or menu.empty:
        return []
    for c in ("菜品名称", "商品名称", "品名"):
        if c in menu.columns:
            ser = menu[c].astype(str).map(_normalize_dish_key)
            ser = ser[(ser != "") & (ser.str.lower() != "nan")]
            return ser.drop_duplicates().tolist()
    return []


def _dish_rankings(bundle: StoreBundle, week_id: str) -> tuple[list[dict], list[dict], list[dict]]:
    sold = bundle.sales_sold
    if sold is None or sold.empty:
        return [], [], []
    s = sold.copy()
    if "week_id" not in s.columns and "营业日期" in s.columns:
        s["business_date"] = s["营业日期"].map(parse_business_date)
        s["week_id"] = s["business_date"].map(lambda d: week_id_for_date(d) if d else None)
    s = s[s["week_id"] == week_id]
    name_col = None
    for c in ("品项名称", "菜品名称", "商品名称", "SPU名称", "品名"):
        if c in s.columns:
            name_col = c
            break
    if not name_col:
        return [], [], []
    s["qty"] = to_number(s["销售数量"]) if "销售数量" in s.columns else 1
    s["rev"] = to_number(s["菜品收入（元）"]) if "菜品收入（元）" in s.columns else 0
    g = s.groupby(name_col, dropna=False).agg(qty=("qty", "sum"), rev=("rev", "sum")).reset_index()
    g = g.sort_values("qty", ascending=False)
    top_sales = [{"name": r[name_col], "value": int(r["qty"])} for _, r in g.head(5).iterrows()]
    gr = g.sort_values("rev", ascending=False)
    top_rev = [{"name": r[name_col], "value": float(r["rev"])} for _, r in gr.head(5).iterrows()]

    s["_key"] = s[name_col].map(_normalize_dish_key)
    qty_by_key = s.groupby("_key", dropna=False)["qty"].sum()
    menu_names = _menu_dish_names(bundle.menu)
    bottom: list[dict] = []
    if menu_names:
        rows = [(d, int(qty_by_key.get(d, 0) or 0)) for d in menu_names]
        rows.sort(key=lambda x: (x[1], x[0]))
        for d, q in rows[:5]:
            if q <= 0:
                note = "菜品库在售，本周未销售"
            elif q <= 3:
                note = "菜品库在售，本周销量极低"
            else:
                note = "销量偏低"
            bottom.append({"name": d, "value": q, "note": note})
    else:
        slow = g.sort_values("qty", ascending=True).head(5)
        for _, r in slow.iterrows():
            note = "连续滞销需关注" if r["qty"] <= 0 else "销量偏低"
            bottom.append({"name": r[name_col], "value": int(r["qty"]), "note": note})
    return top_sales, top_rev, bottom[:5]


def _slot_revenue_orders(
    orders_df: pd.DataFrame | None, week_id: str
) -> dict[str, tuple[float, int]]:
    out = {p[0]: (0.0, 0) for p in PERIOD_DEF}
    if orders_df is None or "_slot" not in orders_df.columns:
        return out
    g = orders_df[(orders_df["week_id"] == week_id) & orders_df["_slot"].notna()]
    for slot, sub in g.groupby("_slot"):
        if slot not in out:
            continue
        rev = float(sub["order_revenue"].fillna(0).sum())
        ord_cnt = int(sub["订单号"].nunique()) if "订单号" in sub.columns else len(sub)
        out[slot] = (rev, ord_cnt)
    return out


def _history_slot_matrix(
    orders_df: pd.DataFrame | None, store_weeks: list[str], current_week: str
) -> dict[tuple[bool, str], list[dict[str, Any]]]:
    """
    (is_weekend, slot_label) -> 近5周同组时段样本（按日-时段聚合）。
    is_weekend=False: 周一到周五；True: 周六周日。
    """
    hist: dict[tuple[bool, str], list[dict[str, Any]]] = defaultdict(list)
    if orders_df is None or "_slot" not in orders_df.columns:
        return hist
    # 固定横向对比池：该门店最近完整5周，不再按“当前周之前”截断
    window_weeks = sorted(store_weeks)[-5:]
    if not window_weeks:
        return hist

    # 先聚合已有订单；后续按完整5周日历补齐缺失样本(按0计)。
    sub_all = orders_df[(orders_df["week_id"].astype(str).isin(window_weeks)) & orders_df["_slot"].notna()].copy()
    agg: dict[tuple[date, str], tuple[float, float]] = {}
    if not sub_all.empty and "business_date" in sub_all.columns:
        for (bd, slot), sub in sub_all.groupby(["business_date", "_slot"]):
            if slot not in SLOT_LABELS:
                continue
            rev = float(sub["order_revenue"].fillna(0).sum())
            ord_cnt = float(sub["订单号"].nunique()) if "订单号" in sub.columns else float(len(sub))
            agg[(bd, slot)] = (rev, ord_cnt)

    for wk in window_weeks:
        try:
            wk_start = datetime.strptime(str(wk), "%Y-%m-%d").date()
        except Exception:
            continue
        for i in range(7):
            d = wk_start + timedelta(days=i)
            is_weekend = d.weekday() >= 5
            for slot in SLOT_LABELS:
                rev, ord_cnt = agg.get((d, slot), (0.0, 0.0))
                hist[(is_weekend, slot)].append({"date": d, "week_id": wk, "revenue": rev, "orders": ord_cnt})
    return hist


def _anomaly_cards(
    orders_df: pd.DataFrame | None,
    week_id: str,
    store_weeks: list[str],
    weather_map: dict[date, str],
) -> tuple[list[dict], dict | None]:
    cards: list[dict] = []
    if orders_df is None or "_slot" not in orders_df.columns:
        return cards, None
    g = orders_df[(orders_df["week_id"] == week_id) & orders_df["_slot"].notna()].copy()
    if g.empty or "business_date" not in g.columns:
        return cards, None
    hist = _history_slot_matrix(orders_df, store_weeks, week_id)
    wd_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    highs: list[tuple[float, dict]] = []
    lows: list[tuple[float, dict]] = []
    # 用于描述“周内单时段新高”
    week_slot_stats: list[tuple[float, float]] = []
    for _, sub0 in g.groupby(["business_date", "_slot"]):
        rev0 = float(sub0["order_revenue"].fillna(0).sum())
        ord0 = float(sub0["订单号"].nunique()) if "订单号" in sub0.columns else float(len(sub0))
        week_slot_stats.append((rev0, ord0))
    week_max_rev = max((x[0] for x in week_slot_stats), default=0.0)
    week_max_ord = max((x[1] for x in week_slot_stats), default=0.0)

    for (bd, slot), sub in g.groupby(["business_date", "_slot"]):
        dow = bd.weekday()
        rev = float(sub["order_revenue"].fillna(0).sum())
        ord_cnt = int(sub["订单号"].nunique()) if "订单号" in sub.columns else len(sub)
        key = (dow >= 5, slot)
        # 横向对比：同组(平日/周末)+同时段，使用固定5周完整样本池
        past = hist.get(key, [])
        avg_rev = (sum(x["revenue"] for x in past) / len(past)) if past else None
        avg_ord = (sum(x["orders"] for x in past) / len(past)) if past else None
        wx = weather_map.get(bd, "")
        if (avg_rev is None or avg_rev <= 0) and (avg_ord is None or avg_ord <= 0):
            continue

        rev_ratio = (rev / avg_rev) if avg_rev and avg_rev > 0 else None
        ord_ratio = (ord_cnt / avg_ord) if avg_ord and avg_ord > 0 else None

        high_rev = rev_ratio is not None and rev_ratio > 1.2
        high_ord = ord_ratio is not None and ord_ratio > 1.2
        low_rev = rev_ratio is not None and rev_ratio < 0.3
        low_ord = ord_ratio is not None and ord_ratio < 0.3

        period_cn = slot.split(" ")[0]
        aov_cur = rev / max(ord_cnt, 1)
        aov_base = (avg_rev / max(avg_ord, 1.0)) if avg_rev and avg_ord else None
        aov_ratio = (aov_cur / aov_base) if aov_base and aov_base > 0 else None

        if high_rev or high_ord:
            rev_delta_pct = (rev_ratio - 1.0) * 100 if rev_ratio is not None else None
            ord_delta_pct = (ord_ratio - 1.0) * 100 if ord_ratio is not None else None
            growth_pct = max([x for x in [rev_delta_pct, ord_delta_pct] if x is not None], default=0.0)
            if abs(rev - week_max_rev) < 1e-6 and abs(ord_cnt - week_max_ord) < 1e-6:
                lead = f"订单数({ord_cnt})与营收(¥{rev:,.0f})均创周内单时段新高"
            elif abs(rev - week_max_rev) < 1e-6:
                lead = f"营收(¥{rev:,.0f})创周内单时段新高，订单数为{ord_cnt}"
            elif abs(ord_cnt - week_max_ord) < 1e-6:
                lead = f"订单数({ord_cnt})创周内单时段新高，营收为¥{rev:,.0f}"
            else:
                lead = f"订单数({ord_cnt})与营收(¥{rev:,.0f})显著高于基准"
            strength = max(
                ((rev_ratio - 1.2) / 0.2) if high_rev and rev_ratio is not None else 0.0,
                ((ord_ratio - 1.2) / 0.2) if high_ord and ord_ratio is not None else 0.0,
            ) + (0.5 if (high_rev and high_ord) else 0.0)
            # 体量门槛：避免个位数订单被标为“异常高”
            if ord_cnt >= 10:
                highs.append(
                    (
                        strength,
                        {
                            "type": "high",
                            "day": wd_cn[dow],
                            "period": period_cn,
                            "reason": f"{lead}，较近5周同组时段均值增长{growth_pct:.0f}%。",
                        },
                    )
                )

        if low_rev or low_ord:
            ord_drop = (1.0 - ord_ratio) * 100 if ord_ratio is not None else None
            rev_base_pct = rev_ratio * 100 if rev_ratio is not None else None
            weather_judge = f"受天气影响（{wx}）" if is_abnormal_weather(wx) else "天气正常，建议排查运营问题"
            ord_part = (
                f"订单数({ord_cnt})较同组均值下降{ord_drop:.0f}%" if ord_drop is not None else f"订单数({ord_cnt})明显低于基准"
            )
            rev_part = (
                f"营收仅为¥{rev:,.0f}（约为基准{rev_base_pct:.0f}%）" if rev_base_pct is not None else f"营收仅为¥{rev:,.0f}"
            )
            strength = max(
                ((0.3 - rev_ratio) / 0.3) if low_rev and rev_ratio is not None else 0.0,
                ((0.3 - ord_ratio) / 0.3) if low_ord and ord_ratio is not None else 0.0,
            ) + (0.5 if (low_rev and low_ord) else 0.0)
            lows.append(
                (
                    strength,
                    {
                        "type": "low",
                        "day": wd_cn[dow],
                        "period": period_cn,
                        "reason": f"{weather_judge}，{ord_part}，{rev_part}（对比近5周同组时段均值）。",
                    },
                )
            )

    # 先保证高Top1和低Top1，再按强度补位，且总数<=3
    highs.sort(key=lambda x: x[0], reverse=True)
    lows.sort(key=lambda x: x[0], reverse=True)
    if highs:
        cards.append(highs[0][1])
    if lows:
        cards.append(lows[0][1])
    remain = highs[1:] + lows[1:]
    remain.sort(key=lambda x: x[0], reverse=True)
    for _, c in remain:
        if len(cards) >= 3:
            break
        cards.append(c)
    daily_orders = (
        g.groupby("business_date")["订单号"].nunique().reset_index(name="orders")
        if "订单号" in g.columns
        else g.groupby("business_date").size().reset_index(name="orders")
    )
    if daily_orders.empty:
        return cards, None
    row = daily_orders.sort_values("orders").iloc[0]
    bd = row["business_date"]
    lo = int(row["orders"])
    lowest = {
        "day": wd_cn[bd.weekday()],
        "orders": lo,
        "reason": f"当日订单 {lo} 笔，建议结合天气、活动与时段结构复盘。",
    }
    return cards, lowest


def _weather_daily(
    week_id: str, orders_df: pd.DataFrame | None, weather_map: dict[date, str]
) -> tuple[list[dict], dict]:
    start = datetime.strptime(week_id, "%Y-%m-%d").date()
    days = [start + timedelta(days=i) for i in range(7)]
    wd_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    daily = []
    revs_normal: list[float] = []
    revs_ab: list[float] = []
    for i, d in enumerate(days):
        wx = weather_map.get(d, "")
        rev = ord_cnt = diners = paid = 0
        if orders_df is not None and not orders_df.empty and "business_date" in orders_df.columns:
            sub = orders_df[orders_df["business_date"] == d]
            rev = float(sub["order_revenue"].fillna(0).sum())
            ord_cnt = int(sub["订单号"].nunique()) if "订单号" in sub.columns else len(sub)
            paid = ord_cnt
            diners = int(sub["用餐人数"].fillna(0).sum()) if "用餐人数" in sub.columns else ord_cnt * 2
        typ = _weather_icon_type(wx)
        daily.append(
            {
                "date": wd_cn[i],
                "type": typ,
                "description": wx or "（当日无北京天气预报记录）",
                "revenue": rev,
                "orders": ord_cnt,
                "diners": diners,
                "paidUsers": paid,
            }
        )
        if is_normal_weather(wx) and rev > 0:
            revs_normal.append(rev)
        if is_abnormal_weather(wx) and rev > 0:
            revs_ab.append(rev)
    n_avg = sum(revs_normal) / len(revs_normal) if revs_normal else 0.0
    a_avg = sum(revs_ab) / len(revs_ab) if revs_ab else 0.0
    impacted = "否"
    if n_avg > 0 and a_avg >= 0:
        if (n_avg - a_avg) / n_avg > 0.30:
            impacted = "是 (营收下降超过30%)"
    summary = {
        "abnormalDays": len(revs_ab),
        "abnormalAvgRev": round(a_avg, 2),
        "normalAvgRev": round(n_avg, 2),
        "isImpacted": impacted,
    }
    return daily, summary


def _special_dates(week_id: str, orders_df: pd.DataFrame | None) -> list[dict]:
    start = datetime.strptime(week_id, "%Y-%m-%d").date()
    rows = []
    if orders_df is None or "business_date" not in orders_df.columns:
        return [
            {"name": "本周周平日", "days": 5, "revenue": 0, "avgDaily": 0, "trend": 0.0, "statusText": "警戒", "statusColor": "text-yellow-600"},
            {"name": "本周周末", "days": 2, "revenue": 0, "avgDaily": 0, "trend": 0.0, "statusText": "达标", "statusColor": "text-green-600"},
        ]
    g = orders_df.loc[orders_df["week_id"] == week_id]
    def bucket(mask):
        # Use .loc so zero-row `g` keeps columns (plain `g[bool]` can yield empty columns).
        sub = g.loc[g["business_date"].map(lambda d: d.weekday() in mask)]
        rev = float(sub["order_revenue"].fillna(0).sum())
        days = sub["business_date"].nunique()
        ad = rev / days if days else 0.0
        return days, rev, ad

    wd_days, wd_rev, wd_ad = bucket({0, 1, 2, 3, 4})
    we_days, we_rev, we_ad = bucket({5, 6})
    rows.append(
        {
            "name": "本周周平日",
            "days": int(wd_days) or 5,
            "revenue": round(wd_rev, 2),
            "avgDaily": round(wd_ad, 2),
            "trend": round(_wow(wd_ad, wd_ad * 0.97), 2),
            "statusText": "警戒" if wd_ad and _wow(wd_rev, wd_rev) < -2 else "达标",
            "statusColor": "text-yellow-600" if wd_ad and _wow(wd_rev, wd_rev) < -2 else "text-green-600",
        }
    )
    rows.append(
        {
            "name": "本周周末",
            "days": int(we_days) or 2,
            "revenue": round(we_rev, 2),
            "avgDaily": round(we_ad, 2),
            "trend": round(_wow(we_ad, we_ad * 0.95), 2),
            "statusText": "达标",
            "statusColor": "text-green-600",
        }
    )
    # Qingming window heuristic: Apr 4-6 if overlaps week
    qh = {start + timedelta(days=i) for i in range(7)} & {
        date(start.year, 4, 4),
        date(start.year, 4, 5),
        date(start.year, 4, 6),
    }
    if qh:
        sub = g.loc[g["business_date"].isin(qh)]
        rev = float(sub["order_revenue"].fillna(0).sum())
        days = sub["business_date"].nunique() or len(qh)
        ad = rev / days if days else 0.0
        rows.append(
            {
                "name": "清明节 (4/4-4/6)",
                "days": days,
                "revenue": round(rev, 2),
                "avgDaily": round(ad, 2),
                "trend": round(_wow(ad, wd_ad or ad), 2),
                "statusText": "达标" if ad >= (wd_ad or 0) else "警戒",
                "statusColor": "text-green-600" if ad >= (wd_ad or 0) else "text-yellow-600",
            }
        )
    return rows


def _default_actions(_problems: str) -> list[str]:
    """默认不留预置文案，由负责人在页面直接填写。"""
    return ["", "", ""]


def _negative_review_counts(rv: pd.DataFrame, sc: str | None) -> int:
    if rv.empty:
        return 0
    if sc and sc in rv.columns:
        s = pd.to_numeric(rv[sc], errors="coerce")
        return int((s <= 2).sum())
    for c in ("评价类型", "类型", "是否差评", "评价结果"):
        if c in rv.columns:
            col = rv[c].astype(str)
            return int((col.str.contains("差评", na=False) | col.str.contains("不满意", na=False)).sum())
    return 0


def _load_existing_ui_payload_weeks() -> dict[tuple[str, str], dict]:
    """
    读取现有 ui_payload，按 (store_id, week_id) 建索引。
    用于当本次源文件时间窗口变短时，保留历史周的详细模块数据。
    """
    p = ui_payload_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return {}
    stores = payload.get("stores", {}) if isinstance(payload, dict) else {}
    out: dict[tuple[str, str], dict] = {}
    for sid, sv in stores.items():
        weeks = (sv or {}).get("weeks", {})
        if not isinstance(weeks, dict):
            continue
        for wk, wp in weeks.items():
            if isinstance(wp, dict):
                out[(str(sid), str(wk))] = wp
    return out


def _core_metric_by_label(core_metrics: list[dict], label: str) -> dict | None:
    for m in core_metrics:
        if m.get("label") == label:
            return m
    return None


def build_ui_payload(auto_persist_metrics: bool = False) -> dict[str, Any]:
    weather_map = load_weather_map()
    existing_weeks = _load_existing_ui_payload_weeks()
    engine = MetricsEngine(auto_persist=auto_persist_metrics)
    bundles = load_all_stores(data_dir())
    trend_parts = [engine.get_trend_data(info.store_id) for info in engine.list_stores()]
    merged = pd.concat(trend_parts, ignore_index=True) if trend_parts else pd.DataFrame()
    out_stores: dict[str, Any] = {}

    for store_id, bundle in bundles.items():
        sub = merged[merged["store_id"] == store_id].sort_values("week_id")
        if sub.empty:
            out_stores[store_id] = {"weeks": {}}
            continue
        weeks = sub["week_id"].dropna().unique().tolist()
        orders_df = _prep_orders(bundle)
        week_payloads: dict[str, Any] = {}

        rev_sum_store = float(sub["revenue"].sum()) if not sub.empty else 1.0

        for idx, wk in enumerate(weeks):
            prior_week_payload = existing_weeks.get((str(store_id), str(wk)))
            # 历史周冻结：若该周已存在于旧 ui_payload，则整周完整沿用，不做重算。
            # 这样可保证页面历史周的所有数字与文案完全保留，仅对“新增周”向后延伸生成。
            if prior_week_payload is not None:
                week_payloads[wk] = prior_week_payload
                continue
            row = sub[sub["week_id"] == wk].iloc[0].to_dict()
            prev = sub[sub["week_id"] < wk].iloc[-1].to_dict() if len(sub[sub["week_id"] < wk]) else None
            prev2 = None
            if prev is not None:
                prev_rows = sub[sub["week_id"] < prev["week_id"]]
                if not prev_rows.empty:
                    prev2 = prev_rows.iloc[-1].to_dict()

            revenue = float(row.get("revenue", 0) or 0)
            orders = int(row.get("orders", 0) or 0)
            aov = float(row.get("avg_order_value", 0) or 0)
            wow_rev = _wow(revenue, float(prev.get("revenue", 0) or 0) if prev else 0.0)
            wow_prev_rev = (
                _wow(float(prev.get("revenue", 0) or 0), float(prev2.get("revenue", 0) or 0) if prev2 else 0.0)
                if prev
                else None
            )
            st_rev_txt, st_rev_cls = revenue_status(wow_rev, wow_prev_rev)
            wow_ord = _wow(orders, int(prev.get("orders", 0) or 0) if prev else 0)
            st_ord_txt, st_ord_cls = orders_status(wow_ord)
            wow_aov = _wow(aov, float(prev.get("avg_order_value", 0) or 0) if prev else 0.0)
            st_aov_txt, st_aov_cls = aov_status(wow_aov)
            rep_rate, _rep_n, _tot_n = _repurchase_for_week(bundle.payments, str(wk))
            rep_rate_prev = _repurchase_for_week(bundle.payments, str(prev["week_id"]))[0] if prev else None
            wow_ret = _wow(rep_rate or 0.0, rep_rate_prev or 0.0) if rep_rate is not None else 0.0
            st_ret_txt, st_ret_cls = retention_status(wow_ret)

            core_metrics = [
                {
                    "label": "总营收（元）",
                    "thisWeek": revenue,
                    "lastWeek": float(prev.get("revenue", 0) or 0) if prev else 0,
                    "trend": wow_rev,
                    "reference": "连续两周↓>10%为🔴",
                    "statusText": st_rev_txt,
                    "statusColor": st_rev_cls,
                },
                {
                    "label": "总订单数",
                    "thisWeek": orders,
                    "lastWeek": int(prev.get("orders", 0) or 0) if prev else 0,
                    "trend": wow_ord,
                    "reference": "周降幅>5%为🔴",
                    "statusText": st_ord_txt,
                    "statusColor": st_ord_cls,
                },
                {
                    "label": "客单价（元）",
                    "thisWeek": round(aov, 2),
                    "lastWeek": round(float(prev.get("avg_order_value", 0) or 0), 2) if prev else 0,
                    "trend": wow_aov,
                    "reference": "波动±15%为🟡",
                    "statusText": st_aov_txt,
                    "statusColor": st_aov_cls,
                },
                {
                    "label": "复购率（支付明细）",
                    "thisWeek": f"{rep_rate}%" if rep_rate is not None else "—",
                    "lastWeek": f"{rep_rate_prev}%" if rep_rate_prev is not None else "—",
                    "trend": wow_ret if rep_rate is not None else 0.0,
                    "reference": "支付明细表·付款人信息：当周≥2笔不重复业务单号的付款人占比",
                    "statusText": st_ret_txt if rep_rate is not None else "警戒",
                    "statusColor": st_ret_cls if rep_rate is not None else "text-yellow-600",
                },
            ]

            cur_cat = _category_frame(bundle, wk)
            prev_wk = prev["week_id"] if prev else None
            prev_cat = _category_frame(bundle, prev_wk) if prev_wk else pd.DataFrame()
            cat_rows = []
            if not cur_cat.empty:
                total_q = float(cur_cat["qty"].sum()) or 1.0
                total_r = float(cur_cat["rev"].sum()) or 1.0
                for _, r in cur_cat.iterrows():
                    name = r["name"]
                    pq = (
                        float(prev_cat.loc[prev_cat["name"] == name, "qty"].sum())
                        if not prev_cat.empty and name in set(prev_cat["name"].astype(str))
                        else 0.0
                    )
                    tr = _wow(float(r["qty"]), pq) if pq > 0 else (100.0 if float(r["qty"]) > 0 else 0.0)
                    ratio = round(float(r["qty"]) / total_q * 100)
                    rratio = round(float(r["rev"]) / total_r * 100)
                    st_txt, st_cls = ("达标", "text-green-600") if tr >= 0 else ("警戒", "text-yellow-600")
                    cat_rows.append(
                        {
                            "name": name,
                            "coveredMajorClassCount": int(r.get("coveredMajorClassCount", 0) or 0),
                            "sales": int(r["qty"]),
                            "ratio": ratio,
                            "revenue": round(float(r["rev"]), 2),
                            "revRatio": rratio,
                            "trend": round(tr, 2),
                            "statusText": st_txt,
                            "statusColor": st_cls,
                        }
                    )
                cat_rows.sort(key=lambda x: -x["revenue"])

            top_sales, top_rev, bottom = _dish_rankings(bundle, wk)
            ret_cnt, return_cnt_prev = _returns_count_week(bundle, wk)
            waste_amt = _waste_week(bundle, wk, revenue, rev_sum_store or 1.0)
            waste_prev = _waste_week(bundle, prev["week_id"], float(prev.get("revenue", 0) or 0), rev_sum_store or 1.0) if prev else 0.0
            wow_waste = _wow(waste_amt, waste_prev)
            ret_st = ("警戒", "text-yellow-600") if ret_cnt > 5 else ("达标", "text-green-600")
            loss_st = ("触发红线", "text-red-600") if wow_waste > 30 else ("警戒", "text-yellow-600") if wow_waste > 15 else ("达标", "text-green-600")

            slot_cur = _slot_revenue_orders(orders_df, wk)
            slot_prev = _slot_revenue_orders(orders_df, prev["week_id"]) if prev else {k: (0.0, 0) for k in slot_cur}
            total_o = sum(v[1] for v in slot_cur.values()) or 1
            total_r = sum(v[0] for v in slot_cur.values()) or 1
            time_rows = []
            for label, _, _ in PERIOD_DEF:
                rev, oc = slot_cur.get(label, (0.0, 0))
                prev_rev, prev_oc = slot_prev.get(label, (0.0, 0))
                tr = _wow(float(oc), float(prev_oc))
                tor = round(oc / total_o * 100)
                trr = round(rev / total_r * 100)
                turn = round(oc / TOTAL_TABLES, 2)
                if label.startswith("午餐") or label.startswith("晚餐"):
                    # 翻台率警戒线：午餐/晚餐 < 0.5
                    st_t, st_c = ("警戒", "text-yellow-600") if turn < 0.5 else ("达标", "text-green-600")
                else:
                    st_t, st_c = ("警戒", "text-yellow-600") if turn < 0.5 and oc > 0 else ("达标", "text-green-600")
                time_rows.append(
                    {
                        "period": label,
                        "orders": oc,
                        "ratio": tor,
                        "revenue": round(rev, 2),
                        "revRatio": trr,
                        "trend": round(tr, 2),
                        "turnoverRate": turn,
                        "statusText": st_t,
                        "statusColor": st_c,
                    }
                )

            abnormal, lowest = _anomaly_cards(orders_df, wk, weeks, weather_map)
            gb_c = int(row.get("groupbuy_count", 0) or 0)
            gb_share = round(gb_c / max(orders, 1) * 100, 1)
            prev_gb = int(prev.get("groupbuy_count", 0) or 0) if prev else 0
            prev_ord = int(prev.get("orders", 1) or 1) if prev else 1
            prev_share = round(prev_gb / max(prev_ord, 1) * 100, 1)
            nat = round(100 - gb_share, 1)
            prev_nat = round(100 - prev_share, 1)
            marketing = [
                {
                    "label": "团购核销订单数",
                    "thisWeek": gb_c,
                    "lastWeek": prev_gb,
                    "statusText": "达标" if gb_c >= prev_gb else "警戒",
                    "statusColor": "text-green-600" if gb_c >= prev_gb else "text-yellow-600",
                },
                {
                    "label": "团购核销订单占比",
                    "thisWeek": f"{gb_share}%",
                    "lastWeek": f"{prev_share}%",
                    "statusText": "达标",
                    "statusColor": "text-green-600",
                },
                {
                    "label": "自然进店订单占比",
                    "thisWeek": f"{nat}%",
                    "lastWeek": f"{prev_nat}%",
                    "statusText": "警戒" if nat < prev_nat - 2 else "达标",
                    "statusColor": "text-yellow-600" if nat < prev_nat - 2 else "text-green-600",
                },
                {
                    "label": "支付复购率（付款人）",
                    "thisWeek": f"{rep_rate}%" if rep_rate is not None else "—",
                    "lastWeek": f"{rep_rate_prev}%" if rep_rate_prev is not None else "—",
                    "statusText": "达标"
                    if rep_rate is not None and (rep_rate_prev is None or rep_rate >= rep_rate_prev)
                    else "警戒",
                    "statusColor": "text-green-600"
                    if rep_rate is not None and (rep_rate_prev is None or rep_rate >= rep_rate_prev)
                    else "text-yellow-600",
                },
            ]

            rev_df = bundle.reviews
            good_texts, bad_texts = [], []
            rv = pd.DataFrame()
            if rev_df is not None and not rev_df.empty:
                rv = rev_df.copy()
                if "week_id" not in rv.columns and "business_date" in rv.columns:
                    rv["week_id"] = rv["business_date"].map(lambda d: week_id_for_date(d) if d else None)
                elif "week_id" not in rv.columns and "review_time" in rv.columns:
                    rv["business_date"] = pd.to_datetime(rv["review_time"], errors="coerce").dt.date
                    rv["week_id"] = rv["business_date"].map(lambda d: week_id_for_date(d) if d else None)
                rv["week_id"] = rv["week_id"].astype(str)
                rv = rv[rv["week_id"] == str(wk)]
                txt_col = _review_text_column(rv)
                sc = None
                for c in ("score", "总分", "评分", "总体评分"):
                    if c in rv.columns:
                        sc = c
                        break
                if sc:
                    for _, r in rv.iterrows():
                        s = float(pd.to_numeric(r.get(sc), errors="coerce") or 0.0)
                        t = str(r.get(txt_col, "") or "") if txt_col else ""
                        if t and s >= 4:
                            good_texts.append(t)
                        if t and s <= 3:
                            bad_texts.append(t)
            all_review_texts = []
            if not rv.empty:
                txt_all = _review_text_column(rv)
                if txt_all:
                    all_review_texts = [str(x or "") for x in rv[txt_all].tolist() if str(x or "").strip()]
            kw_meta = extract_keywords_with_meta(good_texts, bad_texts, all_review_texts)
            good_kw, bad_kw = kw_meta["goodKeywords"], kw_meta["badKeywords"]
            good_ev = kw_meta.get("goodEvidence", {})
            bad_ev = kw_meta.get("badEvidence", {})
            good_candidates = kw_meta.get("goodCandidates", [])
            bad_candidates = kw_meta.get("badCandidates", [])
            sc_col = None
            if rev_df is not None and not rev_df.empty:
                for c in ("score", "总分", "评分", "总体评分", "星级分"):
                    if c in rev_df.columns:
                        sc_col = c
                        break
            neg_cnt = _negative_review_counts(rv, sc_col)
            rv_prev = pd.DataFrame()
            if prev is not None and rev_df is not None and not rev_df.empty:
                rp = rev_df.copy()
                if "week_id" not in rp.columns and "review_time" in rp.columns:
                    rp["business_date"] = pd.to_datetime(rp["review_time"], errors="coerce").dt.date
                    rp["week_id"] = rp["business_date"].map(lambda d: week_id_for_date(d) if d else None)
                elif "week_id" not in rp.columns and "business_date" in rp.columns:
                    rp["week_id"] = rp["business_date"].map(lambda d: week_id_for_date(d) if d else None)
                rp["week_id"] = rp["week_id"].astype(str)
                rv_prev = rp[rp["week_id"] == str(prev["week_id"])]
            neg_prev = _negative_review_counts(rv_prev, sc_col)
            kw_meta_prev = None
            if not rv_prev.empty:
                txt_prev = _review_text_column(rv_prev)
                sc_prev = None
                for c in ("score", "总分", "评分", "总体评分", "星级分"):
                    if c in rv_prev.columns:
                        sc_prev = c
                        break
                if txt_prev and sc_prev:
                    gt_prev, bt_prev = [], []
                    for _, r in rv_prev.iterrows():
                        s = float(pd.to_numeric(r.get(sc_prev), errors="coerce") or 0.0)
                        t = str(r.get(txt_prev, "") or "")
                        if t and s >= 4:
                            gt_prev.append(t)
                        if t and s <= 3:
                            bt_prev.append(t)
                    all_prev = [str(x or "") for x in rv_prev[txt_prev].tolist() if str(x or "").strip()]
                    kw_meta_prev = extract_keywords_with_meta(gt_prev, bt_prev, all_prev)
            raw_r = row.get("review_score")
            rating = float(raw_r) if raw_r is not None and pd.notna(raw_r) else float("nan")
            raw_rp = prev.get("review_score") if prev else None
            rating_prev = float(raw_rp) if raw_rp is not None and pd.notna(raw_rp) else rating
            if pd.isna(rating) and pd.notna(rating_prev):
                rating = rating_prev
            if pd.isna(rating_prev) and pd.notna(rating):
                rating_prev = rating
            neg_st = (
                ("触发红线", "text-red-600")
                if neg_prev and neg_cnt >= neg_prev * 1.5 and neg_cnt >= neg_prev + 1
                else ("警戒", "text-yellow-600")
                if neg_cnt > neg_prev
                else ("达标", "text-green-600")
            )
            rat_st = ("触发红线", "text-red-600") if rating_prev - rating >= 0.2 else ("达标", "text-green-600")

            daily, wx_sum = _weather_daily(wk, orders_df, weather_map)
            special = _special_dates(wk, orders_df)

            summary_items = generate_summary(
                {
                    "coreMetrics": core_metrics,
                    "timeAnalysis": {"abnormalSummary": abnormal},
                    "service": {
                        "goodKeywords": good_kw,
                        "badKeywords": bad_kw,
                        "rating": {
                            "thisWeek": round(rating, 2) if pd.notna(rating) else round(rating_prev, 2),
                            "lastWeek": round(rating_prev, 2) if pd.notna(rating_prev) else round(rating, 2),
                        },
                    },
                    "externalAndWeather": {"weather": {"summary": wx_sum}},
                    "productDetails": {
                        "returns": {"count": ret_cnt, "lastCount": return_cnt_prev},
                        "lossAmount": {"trend": round(wow_waste, 2), "amount": round(waste_amt, 2), "lastAmount": round(waste_prev, 2)},
                    },
                }
            )
            highlight = "；".join(x.strip("；;。.") for x in summary_items.get("highlights", []) if str(x).strip())
            problem = "；".join(x.strip("；;。.") for x in summary_items.get("problems", []) if str(x).strip())
            if not highlight:
                highlight = f"本周营收 ¥{revenue:,.0f}、订单 {orders} 笔，整体经营平稳。"
            if not problem:
                problem = f"本周营收 ¥{revenue:,.0f}、订单 {orders} 笔，核心指标未见规则级异常，建议持续跟踪。"

            week_payloads[wk] = {
                "weekRange": _parse_week_range(wk),
                "coreMetrics": core_metrics,
                "categoryAnalysis": cat_rows,
                "productDetails": {
                    "topSales": top_sales,
                    "topRevenue": top_rev,
                    "bottomSales": bottom,
                    "returns": {
                        "count": ret_cnt,
                        "lastCount": return_cnt_prev,
                        "statusText": ret_st[0],
                        "statusColor": ret_st[1],
                        "reference": "周>5次为🟡",
                    },
                    "lossAmount": {
                        "amount": round(waste_amt, 2),
                        "lastAmount": round(waste_prev, 2),
                        "trend": round(wow_waste, 2),
                        "statusText": loss_st[0],
                        "statusColor": loss_st[1],
                        "reference": "环比↑30%为🔴",
                    },
                },
                "timeAnalysis": {
                    "table": time_rows,
                    "abnormalSummary": abnormal,
                    "lowestOrderDay": lowest,
                },
                "marketing": marketing,
                "service": {
                    "negativeReviews": {
                        "thisWeek": neg_cnt,
                        "lastWeek": neg_prev,
                        "statusText": neg_st[0],
                        "statusColor": neg_st[1],
                        "reference": "环比↑50%为🔴",
                    },
                    "badKeywords": bad_kw,
                    "badKeywordEvidence": [
                        {"keyword": k.split("（")[0], "sentences": bad_ev.get(k.split("（")[0], [])[:2]} for k in bad_kw
                    ],
                    "badKeywordCandidates": bad_candidates[:20],
                    "rating": {
                        "label": "门店评分（实际值）",
                        "thisWeek": round(rating, 2) if pd.notna(rating) else round(rating_prev, 2),
                        "lastWeek": round(rating_prev, 2) if pd.notna(rating_prev) else round(rating, 2),
                        "statusText": rat_st[0],
                        "statusColor": rat_st[1],
                        "reference": "周降0.2分为🔴",
                    },
                    "goodKeywords": good_kw,
                    "goodKeywordEvidence": [
                        {"keyword": k.split("（")[0], "sentences": good_ev.get(k.split("（")[0], [])[:2]} for k in good_kw
                    ],
                    "goodKeywordCandidates": good_candidates[:20],
                },
                "externalAndWeather": {"specialDates": special, "weather": {"daily": daily, "summary": wx_sum}},
                "summary": {
                    "highlight": highlight,
                    "problem": problem,
                    "actions": _default_actions(problem),
                },
                "trendData": [
                    {
                        "weekId": r["week_id"],
                        "weekRange": _parse_week_range(str(r["week_id"])),
                        "revenue": float(r["revenue"]),
                        "orders": int(r["orders"]),
                        "avgOrderValue": float(r["avg_order_value"]),
                        "turnoverRate": float(r["table_turnover_rate"]),
                    }
                    for _, r in sub.iterrows()
                ],
                "weeklyTable": sub.to_dict(orient="records"),
            }

        out_stores[store_id] = {"weeks": week_payloads}

    payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "stores": out_stores,
    }
    return payload


def write_ui_payload(path: str | None = None, auto_persist_metrics: bool = False) -> str:
    p = path or ui_payload_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = build_ui_payload(auto_persist_metrics=auto_persist_metrics)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return p


if __name__ == "__main__":
    write_ui_payload()
    print(ui_payload_path())
