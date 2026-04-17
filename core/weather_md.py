"""Parse data/北京天气预报_近5周.md into date -> weather detail (状况、气温、风力等)。"""
from __future__ import annotations

import os
import re
from datetime import date

from core.paths import weather_md_path


def _parse_cn_month_day(s: str) -> tuple[int, int] | None:
    m = re.match(r"(\d{1,2})月(\d{1,2})日", s.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _strip_nighttime_weather_text(text: str) -> str:
    """
    不采用夜间时段的天气描述：从「天气状况 / 风向风力 / 备注」中剔除含夜间信息的子句，
    仅保留白天相关表述，用于展示与异常天气判定。
    子句按中文逗号、分号切分；任一片段命中夜间关键词则整段丢弃。
    """
    t = (text or "").strip()
    if not t:
        return ""
    # 含「早/白天/午后」等明显昼间信息的子句保留，即使含「夜」字（如极少见的笔误）
    night_only = re.compile(
        r"(夜间|夜里|夜有|夜雨|夜转|夜小|夜阵|后半夜|凌晨|今晚|明晨|明晚|傍晚|夜里|夜晚的)"
    )

    def _clean_segment(seg: str) -> str:
        seg = seg.strip()
        if not seg:
            return ""
        if night_only.search(seg):
            return ""
        return seg

    out_parts: list[str] = []
    for major in re.split(r"[；;]+", t):
        major = major.strip()
        if not major:
            continue
        subs = [s for s in re.split(r"[，,]+", major) if _clean_segment(s)]
        merged = "，".join(subs).strip("，")
        if merged:
            out_parts.append(merged)
    return "；".join(out_parts).strip("；")


def _format_detail(info: dict[str, str]) -> str:
    """单行展示：现象 + 气温 + 风力 + 备注（沙尘/大风等），均为已剔除夜间天气后的字段。"""
    parts: list[str] = []
    ph = (info.get("phenomenon") or "").strip()
    if ph:
        parts.append(ph)
    lo, hi = (info.get("lo") or "").strip(), (info.get("hi") or "").strip()
    if lo or hi:
        parts.append(f"气温 {lo}～{hi}".replace("～～", "～"))
    wind = (info.get("wind") or "").strip()
    if wind:
        parts.append(wind)
    note = (info.get("note") or "").strip()
    if note:
        parts.append(note)
    return "；".join(parts) if parts else ""


def load_weather_detail_map() -> dict[date, dict[str, str]]:
    """
    解析 Markdown 表格：日期、天气状况、最低/最高气温、风向风力、备注。
    年份随「第N周：YYYY年M月D日」标题行推进。
    """
    p = weather_md_path()
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        text = f.read()

    current_year = 2026
    m0 = re.search(r"(20\d{2})年", text)
    if m0:
        current_year = int(m0.group(1))

    out: dict[date, dict[str, str]] = {}
    for line in text.splitlines():
        if line.startswith("##"):
            my = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", line)
            if my:
                current_year = int(my.group(1))
            continue
        if "|" not in line or "日期" in line or "---" in line or ":---" in line:
            continue
        parts = [c.strip() for c in line.split("|")]
        if len(parts) < 6:
            continue
        date_cell = parts[1] if parts and parts[0] == "" else parts[0]
        md = _parse_cn_month_day(date_cell)
        if not md:
            continue
        month, day = md
        try:
            d = date(current_year, month, day)
        except ValueError:
            continue
        phenomenon = _strip_nighttime_weather_text(parts[3] if len(parts) > 3 else "")
        lo = parts[4] if len(parts) > 4 else ""
        hi = parts[5] if len(parts) > 5 else ""
        wind = _strip_nighttime_weather_text(parts[6] if len(parts) > 6 else "")
        note = _strip_nighttime_weather_text(parts[7] if len(parts) > 7 else "")
        out[d] = {
            "phenomenon": phenomenon,
            "lo": lo,
            "hi": hi,
            "wind": wind,
            "note": note,
            "line": _format_detail(
                {"phenomenon": phenomenon, "lo": lo, "hi": hi, "wind": wind, "note": note}
            ),
        }
    return out


def load_weather_map(year: int = 2026) -> dict[date, str]:
    """兼容旧接口：日期 -> 完整天气描述（含气温、风力、备注）。"""
    detail = load_weather_detail_map()
    return {d: (v.get("line") or v.get("phenomenon", "")) for d, v in detail.items()}


def is_abnormal_weather(weather: str) -> bool:
    w = weather or ""
    if any(x in w for x in ("雨", "雪", "雷", "沙尘", "雾", "霾", "大风", "阵风", "寒潮", "对流")):
        return True
    if "高温" in w or "寒潮" in w:
        return True
    return False


def is_normal_weather(weather: str) -> bool:
    w = weather or ""
    return ("晴" in w or "多云" in w or "阴" in w) and not is_abnormal_weather(w)
