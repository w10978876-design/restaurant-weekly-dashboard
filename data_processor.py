"""
兼容入口：历史代码可能 `from data_processor import MetricsEngine`。
实际实现位于 `core/metrics_engine.py`。
"""

from __future__ import annotations

from typing import Any

from core.metrics_engine import MetricsEngine


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        if isinstance(v, str):
            x = v.strip().replace("%", "")
            if not x:
                return default
            return float(x)
        return float(v)
    except Exception:
        return default


def _clean_text_item(s: str) -> str:
    x = str(s or "").strip()
    x = x.rstrip("；;。.")
    return x


def _keyword_themes(items: list[str]) -> str:
    txt = "；".join(items)
    themes: list[str] = []
    if any(k in txt for k in ("环境", "景", "湖", "风景", "氛围")):
        themes.append("环境体验")
    if any(k in txt for k in ("服务", "热情", "周到", "态度")):
        themes.append("服务体验")
    if any(k in txt for k in ("口味", "味道", "好吃", "浓郁", "出品", "菜品", "披萨", "肘子")):
        themes.append("出品口碑")
    if any(k in txt for k in ("排队", "上菜慢", "太挤", "吵", "等待")):
        themes.append("到店与出餐效率")
    return "、".join(themes[:2])


def generate_summary(week_payload: dict[str, Any]) -> dict[str, list[str]]:
    """
    基于 BUSINESS_LOGIC_SPEC.md 自动生成“亮点/问题”列表。

    输入建议为单周 payload（与 `core/dashboard_builder.py` 的单周结构一致）。
    返回:
      {
        "highlights": [...],
        "problems": [...]
      }
    """
    highlights: list[str] = []
    problems: list[str] = []

    # 1) KPI 环比信号
    core_metrics = week_payload.get("coreMetrics", []) or []
    kpi_trend: dict[str, float] = {}
    for m in core_metrics:
        label = str(m.get("label", ""))
        kpi_trend[label] = _to_float(m.get("trend"), 0.0)

    rev_trend = kpi_trend.get("总营收（元）", 0.0)
    ord_trend = kpi_trend.get("总订单数", 0.0)
    if rev_trend > 10:
        highlights.append(f"总营收环比增长{rev_trend:.1f}%，经营表现向好")
    if ord_trend > 10:
        highlights.append(f"总订单数环比增长{ord_trend:.1f}%，客流提升明显")
    if rev_trend < -10:
        problems.append(f"总营收环比下滑{abs(rev_trend):.1f}%，需重点复盘收入结构")
    if ord_trend < -5:
        problems.append(f"总订单数环比下滑{abs(ord_trend):.1f}%，需关注引流与转化")

    # 2) 时段异常检测（优先从 anomalySummary 取结构化结果）
    time_analysis = week_payload.get("timeAnalysis", {}) or {}
    anomalies = time_analysis.get("abnormalSummary", []) or []
    has_peak = False
    has_low = False
    for a in anomalies:
        typ = str(a.get("type", ""))
        reason = str(a.get("reason", "")).strip()
        if typ == "high" and reason:
            has_peak = True
        if typ == "low" and reason:
            has_low = True
    high_cnt = sum(1 for a in anomalies if str(a.get("type", "")) == "high")
    low_cnt = sum(1 for a in anomalies if str(a.get("type", "")) == "low")
    if has_peak and high_cnt >= 2:
        highlights.append(f"本周出现{high_cnt}个高峰时段，时段经营效率突出")
    if has_low:
        problems.append(f"本周出现{low_cnt}个低谷时段，时段经营稳定性不足")

    # 3) 关键词统计（好评/差评）
    service = week_payload.get("service", {}) or {}
    good_keywords = service.get("goodKeywords", []) or []
    bad_keywords = service.get("badKeywords", []) or []
    if good_keywords:
        themes = _keyword_themes(good_keywords)
        ex = "、".join(x.split("（")[0] for x in good_keywords[:2])
        if themes:
            highlights.append(f"顾客好评主要集中在{themes}（如{ex}）")
        else:
            highlights.append(f"顾客好评关键词以{ex}为主")
    if bad_keywords:
        themes = _keyword_themes(bad_keywords)
        ex = "、".join(x.split("（")[0] for x in bad_keywords[:2])
        if themes:
            problems.append(f"顾客差评主要集中在{themes}（如{ex}）")
        else:
            problems.append(f"顾客负面反馈集中在{ex}")

    # 4) 天气影响
    weather = (week_payload.get("externalAndWeather", {}) or {}).get("weather", {}) or {}
    weather_summary = weather.get("summary", {}) or {}
    impacted_text = str(weather_summary.get("isImpacted", "")).strip()
    if impacted_text.startswith("是") or impacted_text.lower() in {"yes", "true"}:
        problems.append("异常天气对营收存在明显负向影响，抗天气波动能力偏弱")

    # 5) 质量下滑与运营损耗信号（规格要求）
    rating = service.get("rating", {}) or {}
    rating_this = _to_float(rating.get("thisWeek"), 0.0)
    rating_last = _to_float(rating.get("lastWeek"), rating_this)
    if rating_last - rating_this > 0.2:
        problems.append(f"门店评分下降{rating_last - rating_this:.2f}分，服务质量有下滑风险")

    product = week_payload.get("productDetails", {}) or {}
    returns = product.get("returns", {}) or {}
    loss = product.get("lossAmount", {}) or {}
    returns_cnt = int(_to_float(returns.get("count"), 0))
    loss_trend = _to_float(loss.get("trend"), 0.0)
    if returns_cnt > 5:
        problems.append(f"退菜/换菜达到{returns_cnt}次，超过每周5次警戒线")
    if loss_trend > 30:
        problems.append(f"报损金额环比上升{loss_trend:.1f}%，触发运营损耗红线")

    # 去重并保持顺序
    def _uniq(items: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for x in items:
            x = _clean_text_item(x)
            if not x:
                continue
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    return {
        "highlights": _uniq(highlights)[:5],
        "problems": _uniq(problems)[:5],
    }


__all__ = ["MetricsEngine", "generate_summary"]
