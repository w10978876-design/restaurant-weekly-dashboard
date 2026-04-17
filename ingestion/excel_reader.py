from __future__ import annotations

import pandas as pd


def clean_column_header(c) -> str:
    """strip；去掉 Excel 里偶发的整列名被包在引号内的情况（如 '类目'）。"""
    s = str(c).strip()
    while len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1].strip()
    return s


def read_sheet(path: str, sheet_name: str, header_row: int = 2) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet_name, header=header_row)
    df.columns = [clean_column_header(c) for c in df.columns]
    return df


def list_sheet_names(path: str) -> list[str]:
    xl = pd.ExcelFile(path)
    return list(xl.sheet_names)


def pick_menu_sheet(path: str) -> str:
    names = list_sheet_names(path)
    for preferred in ("周-菜品库", "Sheet1"):
        if preferred in names:
            return preferred
    return names[0]


def drop_placeholder_tail(df: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    mask = pd.Series(True, index=df.index)
    for c in key_cols:
        if c in df.columns:
            s = df[c].astype(str).str.strip()
            mask &= ~s.isin(["", "nan", "--", "合计"])
            mask &= ~s.str.contains("合计", na=False)
    out = df.loc[mask].copy()
    return out


def to_number(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.replace(",", "", regex=False)
    s = s.str.replace("￥", "", regex=False).str.replace("¥", "", regex=False).str.strip()
    s = s.replace({"--": None, "": None, "nan": None})
    return pd.to_numeric(s, errors="coerce")
