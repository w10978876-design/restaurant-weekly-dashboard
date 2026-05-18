"""Parse data/北京天气预报_近5周.md into date -> weather detail (状况、气温、风力等)。"""
from __future__ import annotations

import os
import re
from datetime import date

from core.paths import weather_md_path

# 气温：仅极端低温/高温计为异常（常规 30℃ 左右晴热不计）
_EXTREME_HI_C = 37.0
_EXTREME_LO_C = 0.0

# 现象里“以晴/多云为主”的常见表述（不含整日强降雨）
_CLEAR_DOMINANT_PREFIXES = (
    "晴",
    "晴间多云",
    "多云间晴",
    "多云转晴",
    "晴转多云",
    "晴间",
    "阴转晴",
    "阴转多云",
    "多云转阴",
    "多云",
    "阴",
)

# 分散/山区小阵雨 —— 不算整日异常
_SCATTER_SHOWER_RE = re.compile(r"(分散|山区|局地|午后).*(雷阵雨|阵雨|小阵雨)")

# 官方预警或整日恶劣天气
_ALERT_RE = re.compile(
    r"(暴雨|大雨|中雨|冰雹|沙尘|寒潮|对流|大雾|浓雾|低能见度)"
    r".*预警|"
    r"(暴雨|大风|雷电|冰雹|沙尘|寒潮)(蓝色|黄色|橙色|红色)?预警"
)

_HEAVY_PRECIP = ("暴雨", "大雨", "中雨", "冻雨", "暴雪", "大雪")


def _parse_cn_month_day(s: str) -> tuple[int, int] | None:
    m = re.match(r"(\d{1,2})月(\d{1,2})日", s.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_iso_date_cell(s: str) -> tuple[int, int, int] | None:
    """表格里常见 `2026-04-13` / `2026/04/13`。"""
    t = s.strip()
    m = re.match(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", t)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _strip_nighttime_weather_text(text: str) -> str:
    """
    不采用夜间时段的天气描述：从「天气状况 / 风向风力 / 备注」中剔除含夜间信息的子句，
    仅保留白天相关表述，用于展示与异常天气判定。
    """
    t = (text or "").strip()
    if not t:
        return ""
    night_only = re.compile(
        r"(夜间|夜里|夜有|夜雨|夜转|夜小|夜阵|后半夜|凌晨|今晚|明晨|明晚|傍晚|夜里|夜晚的)"
    )

    def _clean_segment(seg: str) -> str:
        seg = seg.strip()
        if not seg or night_only.search(seg):
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


def _parse_temp_c(s: str) -> float | None:
    t = re.sub(r"\*+", "", (s or "").strip())
    m = re.search(r"(-?\d+(?:\.\d+)?)", t)
    return float(m.group(1)) if m else None


def _split_weather_line(line: str) -> dict[str, str]:
    """将展示用单行拆回 phenomenon / 气温 / 风力 / 备注（风力段不参与异常判定）。"""
    parts = [p.strip() for p in (line or "").split("；") if p.strip()]
    info = {"phenomenon": "", "lo": "", "hi": "", "wind": "", "note": ""}
    if not parts:
        return info
    info["phenomenon"] = parts[0]
    for p in parts[1:]:
        if p.startswith("气温"):
            m = re.search(r"气温\s*([^～]+)～(.+)", p)
            if m:
                info["lo"], info["hi"] = m.group(1).strip(), m.group(2).strip()
        elif re.search(r"[风级]", p):
            info["wind"] = p
        else:
            info["note"] = f"{info['note']}；{p}".strip("；") if info["note"] else p
    return info


def _is_clear_dominant_phenomenon(phenomenon: str) -> bool:
    p = re.sub(r"\*+", "", (phenomenon or "").strip())
    if not p:
        return False
    for prefix in _CLEAR_DOMINANT_PREFIXES:
        if p == prefix or p.startswith(prefix):
            if any(h in p for h in _HEAVY_PRECIP):
                return False
            if "雨" in p and not _SCATTER_SHOWER_RE.search(p):
                # 如「阴转阵雨」整句有雨但非分散
                if any(x in p for x in ("阵雨", "雷阵雨", "小雨", "雨")):
                    return False
            return True
    return False


def is_abnormal_weather_detail(info: dict[str, str]) -> bool:
    """
    异常天气：整日强降雨/强对流、沙尘霾、官方预警、极端气温等。
    不含：晴/晴间多云/多云转晴、分散山区雷阵雨、仅阵风无预警、常规 30℃ 左右晴热。
    """
    phenomenon = re.sub(r"\*+", "", (info.get("phenomenon") or "").strip())
    note = re.sub(r"\*+", "", (info.get("note") or "").strip())
    combined = f"{phenomenon}；{note}".strip("；")

    if not phenomenon and not note:
        return False

    if _ALERT_RE.search(combined):
        return True

    if any(h in phenomenon for h in _HEAVY_PRECIP):
        return True

    if _is_clear_dominant_phenomenon(phenomenon):
        if _SCATTER_SHOWER_RE.search(phenomenon):
            return False
        return False

    if any(x in phenomenon for x in ("暴雨", "大雨", "中雨", "雷阵雨", "阵雨", "冰雹", "沙尘", "霾")):
        if "小雨" in phenomenon and "预警" not in combined:
            return False
        return True

    if any(x in combined for x in ("沙尘", "霾", "大雾", "浓雾", "低能见度", "寒潮", "对流")):
        return True

    hi = _parse_temp_c(info.get("hi") or "")
    lo = _parse_temp_c(info.get("lo") or "")
    if hi is not None and hi >= _EXTREME_HI_C:
        return True
    if lo is not None and lo <= _EXTREME_LO_C:
        return True

    return False


def is_abnormal_weather(weather: str) -> bool:
    """兼容旧接口：优先按结构化字段判定，不把风力里的「阵风」算作异常。"""
    if not weather:
        return False
    if "；" in weather or weather.startswith("气温"):
        return is_abnormal_weather_detail(_split_weather_line(weather))
    return is_abnormal_weather_detail({"phenomenon": weather, "lo": "", "hi": "", "wind": "", "note": ""})


def is_normal_weather(weather: str) -> bool:
    w = weather or ""
    if "；" in w:
        info = _split_weather_line(w)
        return _is_clear_dominant_phenomenon(info.get("phenomenon", "")) and not is_abnormal_weather_detail(info)
    return ("晴" in w or "多云" in w or "阴" in w) and not is_abnormal_weather(weather)


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
        iso = _parse_iso_date_cell(date_cell)
        if iso:
            y, month, day = iso
            try:
                d = date(y, month, day)
            except ValueError:
                continue
        else:
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
