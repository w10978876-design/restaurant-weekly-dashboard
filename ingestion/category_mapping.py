"""Load 品类映射 Excel: dish→品类、菜品大类→统计品类（多 sheet 自动识别）。"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ingestion.excel_reader import list_sheet_names, read_sheet


def normalize_join_key(s: Any) -> str:
    """与销售明细、映射表 join 时统一键（全角空格、引号等）。"""
    if s is None:
        return ""
    try:
        if pd.isna(s):
            return ""
    except (TypeError, ValueError):
        pass
    t = str(s).strip()
    if t.lower() in ("nan", "none", ""):
        return ""
    t = t.replace("\u3000", "").replace("\xa0", " ")
    t = t.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    return t

_DISH_EXACT = ("菜品名称", "商品名称", "品名", "菜名")
_CAT_EXACT = ("品类", "分类", "类别", "菜品分类", "大类", "商品分类", "档口", "系列")

_CLASS_KEY_EXACT = ("大类名称", "大类", "菜品大类", "商品大类", "菜品类目")
_CAT_TARGET_EXACT = ("类目", "统计品类", "映射品类", "标准品类", "品类")


def _detect_dish_cat_columns(df: pd.DataFrame) -> tuple[str | None, str | None]:
    dish = None
    for ex in _DISH_EXACT:
        for c in df.columns:
            if str(c).strip() == ex:
                dish = c
                break
        if dish:
            break
    if not dish:
        for c in df.columns:
            s = str(c).strip()
            if ("菜品" in s or "商品" in s) and "名称" in s:
                dish = c
                break
    cat = None
    for ex in _CAT_EXACT:
        for c in df.columns:
            if str(c).strip() == ex and c != dish:
                cat = c
                break
        if cat:
            break
    if not cat:
        for c in df.columns:
            s = str(c).strip()
            if c == dish:
                continue
            if s.endswith("分类") or s.endswith("类别") or "品类" in s:
                cat = c
                break
    if dish and not cat:
        for c in df.columns:
            if c == dish:
                continue
            cat = c
            break
    return dish, cat


def _header_norm_for_class_detect(c: str) -> str:
    """列名比较用：全角括号等统一，便于识别「品类(大类)」「品类（大类）」。"""
    s = str(c).strip()
    return s.replace("（", "(").replace("）", ")")


def _detect_class_mapping_columns(df: pd.DataFrame) -> tuple[str | None, str | None]:
    """识别「大类侧列」→「类目侧列」（列顺序可为 大类+类目 或 类目+品类(大类)）。"""
    key = None
    for ex in _CLASS_KEY_EXACT:
        for c in df.columns:
            if str(c).strip() == ex:
                key = c
                break
        if key:
            break
    if not key:
        for c in df.columns:
            st = str(c).strip()
            if st == "类目":
                continue
            s = _header_norm_for_class_detect(c)
            if s.endswith("大类名称") or s.endswith("大类名"):
                key = c
                break
            # 常见「品类(大类)」「品类（大类）」：以「大类)」结尾而非裸「大类」
            if s.endswith("大类)") or s.endswith("大类）"):
                key = c
                break
            if s.endswith("大类") and "名称" not in s:
                key = c
                break
            # 列名含「大类」且不是纯类目列（如 品类(大类)、产品销售大类）
            if "大类" in s and not st.endswith("类目"):
                key = c
                break
    val = None
    if key:
        for ex in _CAT_TARGET_EXACT:
            for c in df.columns:
                if str(c).strip() == ex and c != key:
                    val = c
                    break
            if val:
                break
    if key and not val:
        for c in df.columns:
            if c == key:
                continue
            if "品类" in str(c):
                val = c
                break
    if key and not val:
        others = [c for c in df.columns if c != key]
        tagged = [c for c in others if any(t in str(c) for t in ("类目", "统计", "映射", "标准", "品类"))]
        if len(tagged) == 1:
            val = tagged[0]
        elif len(others) == 1:
            val = others[0]
    if key and not val:
        # 列名如「前台类目」「经营类目」等：以「类目」结尾
        ends_cat = [c for c in df.columns if c != key and str(c).strip().endswith("类目")]
        if len(ends_cat) == 1:
            val = ends_cat[0]
    return key, val


def _read_class_mapping_df(path: str, sheet: str) -> pd.DataFrame | None:
    """
    品类映射各文件表头行不统一：默认第三行表头(2)与订单等一致，但很多映射表为第一行。
    依次尝试 2/0/1/3，直到能识别出「大类键 + 类目值」列对。
    """
    for hr in (2, 0, 1, 3):
        try:
            df = read_sheet(path, sheet, header_row=hr)
        except Exception:
            continue
        if df.empty or len(df.columns) < 2:
            continue
        k, v = _detect_class_mapping_columns(df)
        if k and v:
            return df
    return None


def _class_mapping_key_priority(key_col: str) -> int:
    """多 sheet 时优先采用与销售明细「大类名称」同维度的映射表。"""
    s = str(key_col).strip()
    if s == "大类名称" or s.endswith("大类名称"):
        return 2
    if s in ("大类", "菜品大类", "商品大类", "菜品类目"):
        return 1
    return 0


def load_category_mapping(path: str) -> pd.DataFrame | None:
    """菜品名称 → 品类（用于与菜品库、名称维度的辅助对照）。"""
    try:
        names = list_sheet_names(path)
    except Exception:
        return None
    best: tuple[int, pd.DataFrame] | None = None
    for sheet in names:
        if str(sheet).startswith("~"):
            continue
        try:
            df = read_sheet(path, sheet)
        except Exception:
            continue
        dish, cat = _detect_dish_cat_columns(df)
        if not dish or not cat:
            continue
        out = df[[dish, cat]].copy()
        out.columns = ["菜品名称", "品类"]
        out["菜品名称"] = out["菜品名称"].astype(str).str.strip()
        out["品类"] = out["品类"].astype(str).str.strip()
        out = out[(out["菜品名称"] != "") & (out["菜品名称"].str.lower() != "nan")]
        out = out[~out["菜品名称"].str.contains("合计", na=False)]
        out = out.drop_duplicates(subset=["菜品名称"], keep="last")
        if out.empty:
            continue
        sc = len(out)
        if best is None or sc > best[0]:
            best = (sc, out)
    return best[1] if best else None


def load_class_category_mapping(path: str) -> pd.DataFrame | None:
    """
    大类名称/菜品大类等 → 类目。
    - 每个 sheet 尝试多行表头，避免映射表与「菜品销售明细」表头行不一致导致整表读错。
    - 合并所有可识别 sheet 的行，按 normalize_join_key 去重；同键时保留「键列优先级」更高的行。
    """
    try:
        names = list_sheet_names(path)
    except Exception:
        return None
    pieces: list[tuple[int, pd.DataFrame]] = []
    for sheet in names:
        if str(sheet).startswith("~"):
            continue
        df = _read_class_mapping_df(path, sheet)
        if df is None:
            continue
        k, v = _detect_class_mapping_columns(df)
        if not k or not v:
            continue
        try:
            out = df[[k, v]].copy()
        except KeyError:
            continue
        out.columns = ["菜品大类", "类目"]
        out["菜品大类"] = out["菜品大类"].astype(str).str.strip()
        out["类目"] = out["类目"].astype(str).str.strip()
        out = out[(out["菜品大类"] != "") & (out["菜品大类"].str.lower() != "nan")]
        out = out[~out["菜品大类"].str.contains("合计", na=False)]
        out = out.drop_duplicates(subset=["菜品大类"], keep="last")
        if out.empty:
            continue
        pri = _class_mapping_key_priority(k)
        pieces.append((pri, out))

    if not pieces:
        return None
    acc = pd.concat([p[1].assign(__map_pri=p[0]) for p in pieces], ignore_index=True)
    acc["_nk"] = acc["菜品大类"].map(normalize_join_key)
    acc = acc[acc["_nk"] != ""]
    if acc.empty:
        return None
    acc = acc.sort_values(["_nk", "__map_pri"], ascending=[True, False])
    acc = acc.drop_duplicates(subset=["_nk"], keep="first")
    acc = acc.drop(columns=["__map_pri", "_nk"])
    return acc
