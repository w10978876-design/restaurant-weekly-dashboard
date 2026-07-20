"""
销售/订单口径（看板核心指标）：

1) 销售额 = 订单表全部状态「订单收入（元）」之和
           − 菜品/品项销售明细中品项名称含「团餐活动」的品项收入之和
2) 订单数 = 已结账订单数
           − 敏感操作含「整单退」的订单
           − 品项名称含「团餐活动」的订单
3) 对账：去除团餐活动后，订单收入合计 vs 品项/菜品收入合计应一致
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

from ingestion.excel_reader import to_number

logger = logging.getLogger(__name__)

GROUP_MEAL_TOKEN = "团餐活动"
FULL_REFUND_TOKEN = "整单退"
RECON_TOLERANCE = 0.05  # 允许分位误差


def normalize_order_id(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, (int,)):
        return str(val)
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return str(val).strip()
    s = str(val).strip()
    if not s or s.lower() in {"nan", "none", "--"}:
        return ""
    if s.endswith(".0") and s[:-2].replace("-", "", 1).isdigit():
        return s[:-2]
    return s


def _dish_name_column(sales: pd.DataFrame) -> str | None:
    for c in ("品项名称", "菜品名称", "商品名称", "SPU名称", "品名"):
        if c in sales.columns:
            return c
    return None


def _sales_order_id_column(sales: pd.DataFrame) -> str | None:
    for c in ("订单号", "订单编号"):
        if c in sales.columns:
            return c
    return None


def _sales_revenue_series(sales: pd.DataFrame) -> pd.Series:
    if "dish_revenue" in sales.columns:
        return to_number(sales["dish_revenue"]).fillna(0.0)
    if "菜品收入（元）" in sales.columns:
        return to_number(sales["菜品收入（元）"]).fillna(0.0)
    for c in ("品项收入(元)", "菜品收入(元)", "销售金额(元)", "营业额(元)", "销售额（元）"):
        if c in sales.columns:
            return to_number(sales[c]).fillna(0.0)
    return pd.Series(0.0, index=sales.index)


def group_meal_mask(sales: pd.DataFrame | None) -> pd.Series:
    if sales is None or sales.empty:
        return pd.Series(dtype=bool)
    name_c = _dish_name_column(sales)
    if not name_c:
        return pd.Series(False, index=sales.index)
    return sales[name_c].astype(str).str.contains(GROUP_MEAL_TOKEN, na=False)


def group_meal_order_ids(sales: pd.DataFrame | None, week_id: str | None = None) -> set[str]:
    if sales is None or sales.empty:
        return set()
    sub = sales
    if week_id is not None and "week_id" in sales.columns:
        sub = sales[sales["week_id"].astype(str) == str(week_id)]
    mask = group_meal_mask(sub)
    if not mask.any():
        return set()
    id_c = _sales_order_id_column(sub)
    if not id_c:
        return set()
    return {normalize_order_id(v) for v in sub.loc[mask, id_c].tolist() if normalize_order_id(v)}


def group_meal_amount(
    sales: pd.DataFrame | None,
    week_id: str | None = None,
    on_date: date | None = None,
) -> float:
    if sales is None or sales.empty:
        return 0.0
    sub = sales
    if week_id is not None and "week_id" in sales.columns:
        sub = sub[sub["week_id"].astype(str) == str(week_id)]
    if on_date is not None and "business_date" in sub.columns:
        sub = sub[sub["business_date"] == on_date]
    mask = group_meal_mask(sub)
    if not mask.any():
        return 0.0
    return float(_sales_revenue_series(sub.loc[mask]).sum())


def full_refund_order_ids(orders: pd.DataFrame | None, week_id: str | None = None) -> set[str]:
    if orders is None or orders.empty or "敏感操作" not in orders.columns:
        return set()
    sub = orders
    if week_id is not None and "week_id" in orders.columns:
        sub = orders[orders["week_id"].astype(str) == str(week_id)]
    if "订单号" not in sub.columns:
        return set()
    mask = sub["敏感操作"].astype(str).str.contains(FULL_REFUND_TOKEN, na=False)
    return {normalize_order_id(v) for v in sub.loc[mask, "订单号"].tolist() if normalize_order_id(v)}


def settled_order_ids(orders: pd.DataFrame | None, week_id: str | None = None) -> set[str]:
    if orders is None or orders.empty or "订单号" not in orders.columns:
        return set()
    sub = orders
    if week_id is not None and "week_id" in orders.columns:
        sub = orders[orders["week_id"].astype(str) == str(week_id)]
    if "订单状态" in sub.columns:
        sub = sub[sub["订单状态"].astype(str) == "已结账"]
    return {normalize_order_id(v) for v in sub["订单号"].tolist() if normalize_order_id(v)}


def all_status_order_revenue(
    orders: pd.DataFrame | None,
    week_id: str | None = None,
    on_date: date | None = None,
) -> float:
    """全部订单状态的订单收入合计（不筛已结账）。"""
    if orders is None or orders.empty:
        return 0.0
    sub = orders
    if week_id is not None and "week_id" in orders.columns:
        sub = sub[sub["week_id"].astype(str) == str(week_id)]
    if on_date is not None and "business_date" in sub.columns:
        sub = sub[sub["business_date"] == on_date]
    if sub.empty:
        return 0.0
    if "order_revenue" in sub.columns:
        return float(to_number(sub["order_revenue"]).fillna(0).sum())
    if "订单收入（元）" in sub.columns:
        return float(to_number(sub["订单收入（元）"]).fillna(0).sum())
    return 0.0


def sales_item_revenue(
    sales: pd.DataFrame | None,
    week_id: str | None = None,
    exclude_group_meal: bool = False,
) -> float:
    if sales is None or sales.empty:
        return 0.0
    sub = sales
    if week_id is not None and "week_id" in sales.columns:
        sub = sub[sub["week_id"].astype(str) == str(week_id)]
    if exclude_group_meal:
        sub = sub.loc[~group_meal_mask(sub)]
    if sub.empty:
        return 0.0
    return float(_sales_revenue_series(sub).sum())


def adjusted_revenue(
    orders: pd.DataFrame | None,
    sales: pd.DataFrame | None,
    week_id: str | None = None,
    on_date: date | None = None,
) -> float:
    """销售额 = 全状态订单收入 − 团餐活动品项收入。"""
    base = all_status_order_revenue(orders, week_id=week_id, on_date=on_date)
    deduct = group_meal_amount(sales, week_id=week_id, on_date=on_date)
    return round(base - deduct, 2)


def adjusted_order_count(
    orders: pd.DataFrame | None,
    sales: pd.DataFrame | None,
    week_id: str | None = None,
) -> int:
    """
    订单数 = 已结账 − 敏感操作含整单退 − 团餐活动订单。
    用集合差集，避免「整单退」本身不在已结账集合时被误减。
    """
    settled = settled_order_ids(orders, week_id=week_id)
    refunds = full_refund_order_ids(orders, week_id=week_id)
    meals = group_meal_order_ids(sales, week_id=week_id)
    return len(settled - refunds - meals)


def reconcile_revenue(
    orders: pd.DataFrame | None,
    sales: pd.DataFrame | None,
    week_id: str,
    store_id: str = "",
) -> dict[str, Any]:
    """
    去除团餐活动后：
    - 订单侧：全状态订单收入 − 团餐活动品项金额
    - 品项侧：品项/菜品收入中非团餐活动合计
    """
    order_raw = all_status_order_revenue(orders, week_id=week_id)
    meal_amt = group_meal_amount(sales, week_id=week_id)
    order_adj = round(order_raw - meal_amt, 2)
    sales_adj = round(sales_item_revenue(sales, week_id=week_id, exclude_group_meal=True), 2)
    diff = round(order_adj - sales_adj, 2)
    ok = abs(diff) <= RECON_TOLERANCE
    result = {
        "week_id": str(week_id),
        "store_id": store_id,
        "orderRevenueAllStatus": round(order_raw, 2),
        "groupMealAmount": round(meal_amt, 2),
        "orderRevenueAdjusted": order_adj,
        "salesRevenueAdjusted": sales_adj,
        "diff": diff,
        "matched": ok,
    }
    if sales is None or (isinstance(sales, pd.DataFrame) and sales.empty):
        # 无销售明细时跳过告警（如数据不全）
        result["matched"] = True
        result["skipped"] = True
        return result
    if not ok:
        logger.warning(
            "[销售对账不一致] store=%s week=%s 订单调整后=%.2f 品项调整后=%.2f 差额=%.2f",
            store_id,
            week_id,
            order_adj,
            sales_adj,
            diff,
        )
    return result
