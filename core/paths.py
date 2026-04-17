from __future__ import annotations

import os


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def data_dir() -> str:
    return os.path.join(repo_root(), "data")


def warehouse_dir() -> str:
    return os.path.join(data_dir(), "warehouse")


def weekly_metrics_path() -> str:
    return os.path.join(warehouse_dir(), "weekly_metrics.json")


def action_plans_path() -> str:
    return os.path.join(warehouse_dir(), "action_plans.json")


def ui_payload_path() -> str:
    return os.path.join(warehouse_dir(), "ui_payload.json")


def weather_md_path() -> str:
    return os.path.join(data_dir(), "北京天气预报_近5周.md")
