"""Status labels per BUSINESS_LOGIC_SPEC §1."""
from __future__ import annotations


def _cls(text: str) -> str:
    if text == "触发红线":
        return "text-red-600"
    if text == "警戒":
        return "text-yellow-600"
    return "text-green-600"


def revenue_status(wow: float, wow_prev: float | None) -> tuple[str, str]:
    if wow_prev is not None and wow < -10 and wow_prev < -10:
        return "触发红线", _cls("触发红线")
    if wow > 0:
        return "达标", _cls("达标")
    if abs(wow) <= 15:
        return "警戒", _cls("警戒")
    return "警戒", _cls("警戒")


def orders_status(wow: float) -> tuple[str, str]:
    if wow < -5:
        return "触发红线", _cls("触发红线")
    if -5 <= wow <= -2:
        return "警戒", _cls("警戒")
    if wow > 0:
        return "达标", _cls("达标")
    return "警戒", _cls("警戒")


def aov_status(wow: float) -> tuple[str, str]:
    if abs(wow) <= 5:
        return "达标", _cls("达标")
    if abs(wow) <= 15:
        return "警戒", _cls("警戒")
    return "警戒", _cls("警戒")


def retention_status(wow: float) -> tuple[str, str]:
    if wow < -5:
        return "警戒", _cls("警戒")
    if wow > 0:
        return "达标", _cls("达标")
    return "达标", _cls("达标")
