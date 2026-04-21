from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable


@dataclass
class StoreDataPaths:
    store_key: str
    display_name: str
    directory: str


def list_store_dirs(data_root: str) -> list[StoreDataPaths]:
    out: list[StoreDataPaths] = []
    if not os.path.isdir(data_root):
        return out
    for name in sorted(os.listdir(data_root)):
        path = os.path.join(data_root, name)
        if not os.path.isdir(path):
            continue
        if name.startswith(".") or name == "warehouse":
            continue
        out.append(StoreDataPaths(store_key=name, display_name=name, directory=path))
    return out


def pick_latest(paths: list[str], predicate: Callable[[str], bool]) -> str | None:
    candidates = [p for p in paths if predicate(os.path.basename(p))]
    if not candidates:
        return None
    return max(candidates, key=lambda p: os.path.getmtime(p))


def resolve_store_files(store_dir: str) -> dict[str, str | None]:
    files = [
        os.path.join(store_dir, f)
        for f in os.listdir(store_dir)
        if f.lower().endswith(".xlsx") and not f.startswith("~$")
    ]

    def has(*parts: str) -> callable:
        def _fn(name: str) -> bool:
            return all(p in name for p in parts)

        return _fn

    return {
        "orders": pick_latest(files, has("店内订单明细", "全部订单"))
        or pick_latest(files, has("订单明细")),
        "payments": pick_latest(files, has("支付明细")),
        "sales": pick_latest(files, has("菜品销售明细"))
        or pick_latest(files, has("品项销售明细")),
        "waste": pick_latest(files, has("菜品报损")),
        "reviews": pick_latest(files, lambda n: ("评价管理" in n) or ("店内评价" in n)),
        "menu": pick_latest(files, has("菜品库")),
        "category_map": pick_latest(files, has("品类映射")),
        "groupbuy": pick_latest(files, has("团购核销明细")),
    }
