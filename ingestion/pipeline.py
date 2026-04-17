from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from core.weeks import parse_business_date, week_id_for_date
from ingestion.category_mapping import load_category_mapping, load_class_category_mapping
from ingestion.excel_reader import (
    drop_placeholder_tail,
    pick_menu_sheet,
    read_sheet,
    to_number,
)
from ingestion.file_resolver import resolve_store_files


@dataclass
class StoreBundle:
    store_key: str
    store_dir: str
    resolved_paths: dict[str, str | None]
    orders: pd.DataFrame | None
    payments: pd.DataFrame | None
    sales_sold: pd.DataFrame | None
    sales_return: pd.DataFrame | None
    waste: pd.DataFrame | None
    discounts: pd.DataFrame | None
    groupbuy: pd.DataFrame | None
    reviews: pd.DataFrame | None
    menu: pd.DataFrame | None
    category_map: pd.DataFrame | None
    category_class_map: pd.DataFrame | None
    store_rating_sheet: pd.DataFrame | None


def _safe_read_orders(path: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    df = read_sheet(path, "订单明细")
    df = drop_placeholder_tail(df, ["订单号", "营业日期"])
    if "营业日期" in df.columns:
        df["business_date"] = df["营业日期"].map(parse_business_date)
        df["week_id"] = df["business_date"].map(lambda d: week_id_for_date(d) if d else None)
    if "订单收入（元）" in df.columns:
        df["order_revenue"] = to_number(df["订单收入（元）"])
    elif "支付合计（元）" in df.columns:
        df["order_revenue"] = to_number(df["支付合计（元）"])
    else:
        df["order_revenue"] = float("nan")

    dish = read_sheet(path, "菜品明细")
    dish = drop_placeholder_tail(dish, ["订单编号"])
    item = read_sheet(path, "优惠明细")
    item = drop_placeholder_tail(item, ["订单编号"])
    if "折扣优惠金额（元）" in item.columns:
        item["discount_amount"] = to_number(item["折扣优惠金额（元）"])
    return df, dish, item


def _safe_read_payments(path: str) -> pd.DataFrame | None:
    df = read_sheet(path, "支付明细表")
    df = drop_placeholder_tail(df, ["业务单号"])
    if "交易金额(元)" in df.columns:
        df["pay_amount"] = to_number(df["交易金额(元)"])
    if "交易时间" in df.columns:
        df["pay_time"] = pd.to_datetime(df["交易时间"], errors="coerce")
        df["business_date"] = df["pay_time"].dt.date
        df["week_id"] = df["business_date"].map(lambda d: week_id_for_date(d) if pd.notna(d) and d else None)
    for c in df.columns:
        if str(c).strip() == "付款人信息":
            df["_payer"] = df[c].astype(str).str.strip()
            break
    return df


def _safe_read_sales(path: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    sold = read_sheet(path, "已销售")
    sold = drop_placeholder_tail(sold, ["订单编号", "营业日期"])
    if "营业日期" in sold.columns:
        sold["business_date"] = sold["营业日期"].map(parse_business_date)
        sold["week_id"] = sold["business_date"].map(lambda d: week_id_for_date(d) if d else None)
    if "菜品收入（元）" in sold.columns:
        sold["dish_revenue"] = to_number(sold["菜品收入（元）"])
    if "销售数量" in sold.columns:
        sold["qty"] = to_number(sold["销售数量"])

    ret = read_sheet(path, "退菜")
    ret = drop_placeholder_tail(ret, ["订单编号", "营业日期"])
    if "营业日期" in ret.columns:
        ret["business_date"] = ret["营业日期"].map(parse_business_date)
        ret["week_id"] = ret["business_date"].map(lambda d: week_id_for_date(d) if d else None)
    if "菜品收入（元）" in ret.columns:
        ret["dish_revenue"] = to_number(ret["菜品收入（元）"])
    return sold, ret


def _safe_read_waste(path: str) -> pd.DataFrame | None:
    df = read_sheet(path, "菜品报损统计")
    df = drop_placeholder_tail(df, ["菜品名称", "报损金额"])
    if "菜品名称" in df.columns:
        df = df[~df["菜品名称"].astype(str).str.contains("合计", na=False)]
    if "报损金额" in df.columns:
        df["waste_amount"] = to_number(df["报损金额"])
    if "报损数量" in df.columns:
        df["waste_qty"] = to_number(df["报损数量"])
    return df


def _safe_read_groupbuy(path: str) -> pd.DataFrame | None:
    df = read_sheet(path, "团购核销明细")
    df = drop_placeholder_tail(df, ["核销/撤销时间"])
    if "团购平台" in df.columns:
        df = df[~df["团购平台"].astype(str).str.contains("合计", na=False)]
    if "核销/撤销时间" in df.columns:
        df["verify_time"] = pd.to_datetime(df["核销/撤销时间"], errors="coerce")
        df["business_date"] = df["verify_time"].dt.date
        df["week_id"] = df["business_date"].map(lambda d: week_id_for_date(d) if pd.notna(d) and d else None)
    return df


def _safe_read_reviews(path: str) -> pd.DataFrame | None:
    """店内评价管理 · 店内评价明细 sheet。"""
    df = read_sheet(path, "店内评价明细")
    time_c = None
    for c in ("评价时间", "评价日期", "提交时间", "创建时间", "时间"):
        if c in df.columns:
            time_c = c
            break
    key_cols = [c for c in [time_c, "总分", "score", "评分"] if c and c in df.columns]
    if len(key_cols) >= 2:
        df = drop_placeholder_tail(df, key_cols[:2])
    elif key_cols:
        df = drop_placeholder_tail(df, key_cols)
    if time_c:
        df["review_time"] = pd.to_datetime(df[time_c], errors="coerce")
        df["business_date"] = df["review_time"].dt.date
        df["week_id"] = df["business_date"].map(lambda d: week_id_for_date(d) if pd.notna(d) and d else None)
    score_c = None
    for c in ("总分", "score", "评分", "星级", "总体评分", "满意度"):
        if c in df.columns:
            score_c = c
            break
    if score_c:
        df["score"] = to_number(df[score_c])
    return df


def _safe_read_store_rating_sheet(path: str) -> pd.DataFrame | None:
    """店内评价管理 xlsx 中的「门店评分」sheet：取「实际值」列，按日期落在自然周。"""
    from ingestion.excel_reader import list_sheet_names

    def _parse_store_rating_ts(raw, default_year: int) -> pd.Timestamp:
        """兼容「4 月 8 日」/「4月8日」等无年份中文日期。"""
        ts = pd.to_datetime(raw, errors="coerce")
        if pd.notna(ts):
            return ts
        s = str(raw).strip()
        m = re.search(r"(?:(\d{4})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
        if not m:
            return pd.NaT
        y = int(m.group(1)) if m.group(1) else int(default_year)
        mm = int(m.group(2))
        dd = int(m.group(3))
        try:
            return pd.Timestamp(datetime(y, mm, dd))
        except ValueError:
            return pd.NaT

    try:
        names = list_sheet_names(path)
    except Exception:
        return None
    sheet = None
    for n in names:
        ns = str(n).strip()
        if ns == "门店评分" or ("门店" in ns and "评分" in ns):
            sheet = n
            break
    if not sheet:
        return None
    m_year = re.search(r"(20\d{2})", os.path.basename(path))
    default_year = int(m_year.group(1)) if m_year else datetime.now().year
    # 「门店评分」sheet 的表头行在不同导出里不固定（常见为第2行），依次尝试。
    for header_row in (2, 1, 0, 3):
        try:
            df = read_sheet(path, sheet, header_row=header_row)
        except Exception:
            continue
        val_col = None
        for c in df.columns:
            if str(c).strip() == "实际值":
                val_col = c
                break
        if not val_col:
            continue
        date_col = None
        for c in df.columns:
            t = str(c).strip()
            if t in ("日期", "统计日期", "数据日期", "业务日期", "记录日期", "时间"):
                date_col = c
                break
        if not date_col:
            continue
        out = df[[date_col, val_col]].copy()
        out.columns = ["_dt_raw", "实际值"]
        out["_ts"] = out["_dt_raw"].map(lambda x: _parse_store_rating_ts(x, default_year))
        out = out[out["_ts"].notna()].copy()
        if out.empty:
            continue
        out["business_date"] = out["_ts"].dt.date
        out["week_id"] = out["business_date"].map(lambda d: week_id_for_date(d) if d else None)
        out["实际值"] = to_number(out["实际值"])
        out = out[out["week_id"].notna()]
        out = out[out["实际值"].notna()]
        if out.empty:
            continue
        return out[["business_date", "week_id", "_ts", "实际值"]]
    return None


def _safe_read_menu(path: str) -> pd.DataFrame | None:
    sheet = pick_menu_sheet(path)
    df = read_sheet(path, sheet)
    if "价格" in df.columns:
        df["list_price"] = to_number(df["价格"])
    return df


def _safe_read_category_map(path: str) -> pd.DataFrame | None:
    return load_category_mapping(path)


def load_store_bundle(store_key: str, store_dir: str) -> StoreBundle:
    resolved = resolve_store_files(store_dir)

    orders = disc = None
    if resolved.get("orders"):
        orders, _, disc = _safe_read_orders(resolved["orders"])

    payments = _safe_read_payments(resolved["payments"]) if resolved.get("payments") else None
    sold = ret = None
    if resolved.get("sales"):
        sold, ret = _safe_read_sales(resolved["sales"])
    waste = _safe_read_waste(resolved["waste"]) if resolved.get("waste") else None
    gb = _safe_read_groupbuy(resolved["groupbuy"]) if resolved.get("groupbuy") else None
    rev = _safe_read_reviews(resolved["reviews"]) if resolved.get("reviews") else None
    menu = _safe_read_menu(resolved["menu"]) if resolved.get("menu") else None
    cmap = _safe_read_category_map(resolved["category_map"]) if resolved.get("category_map") else None
    cmap_class = load_class_category_mapping(resolved["category_map"]) if resolved.get("category_map") else None
    srs = _safe_read_store_rating_sheet(resolved["reviews"]) if resolved.get("reviews") else None

    return StoreBundle(
        store_key=store_key,
        store_dir=store_dir,
        resolved_paths=resolved,
        orders=orders,
        payments=payments,
        sales_sold=sold,
        sales_return=ret,
        waste=waste,
        discounts=disc,
        groupbuy=gb,
        reviews=rev,
        menu=menu,
        category_map=cmap,
        category_class_map=cmap_class,
        store_rating_sheet=srs,
    )


def load_all_stores(data_root: str) -> dict[str, StoreBundle]:
    out: dict[str, StoreBundle] = {}
    if not os.path.isdir(data_root):
        return out
    for name in sorted(os.listdir(data_root)):
        d = os.path.join(data_root, name)
        if not os.path.isdir(d) or name.startswith(".") or name == "warehouse":
            continue
        out[name] = load_store_bundle(name, d)
    return out
