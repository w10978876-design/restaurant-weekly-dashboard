from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from core.dashboard_builder import write_ui_payload
from core.metrics_engine import MetricsEngine
from core.paths import action_plans_path, ui_payload_path, weekly_metrics_path


def _backup_file(src: Path, backup_dir: Path) -> Path | None:
    if not src.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backup_dir / f"{src.stem}_{stamp}{src.suffix}"
    shutil.copy2(src, dst)
    return dst


def _safe_json_rows(path: Path, key: str) -> int:
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        arr = payload.get(key, [])
        return len(arr) if isinstance(arr, list) else 0
    except Exception:
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly update with backup and validations.")
    parser.add_argument("--skip-backup", action="store_true", help="Skip backup step.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    backup_dir = repo_root / "data" / "warehouse" / "backups"

    metrics_path = Path(weekly_metrics_path())
    plans_path = Path(action_plans_path())
    payload_path = Path(ui_payload_path())

    before_metrics_rows = _safe_json_rows(metrics_path, "rows")
    before_plan_rows = _safe_json_rows(plans_path, "items")

    if not args.skip_backup:
        metrics_bak = _backup_file(metrics_path, backup_dir)
        plans_bak = _backup_file(plans_path, backup_dir)
        print(f"[backup] weekly_metrics: {metrics_bak or 'not found'}")
        print(f"[backup] action_plans:  {plans_bak or 'not found'}")

    # 1) 触发周度指标增量合并并持久化 weekly_metrics.json
    engine = MetricsEngine(auto_persist=True)
    ok, err = engine.persist_status()
    if not ok:
        raise RuntimeError(f"Persist weekly metrics failed: {err}")

    # 2) 生成前端主 payload（不会写 action_plans）
    out = write_ui_payload(str(payload_path), auto_persist_metrics=False)

    after_metrics_rows = _safe_json_rows(metrics_path, "rows")
    after_plan_rows = _safe_json_rows(plans_path, "items")

    print(f"[done] ui_payload: {out}")
    print(
        f"[check] weekly_metrics rows: {before_metrics_rows} -> {after_metrics_rows} "
        f"({'OK' if after_metrics_rows >= before_metrics_rows else 'WARN'})"
    )
    print(
        f"[check] action_plans items: {before_plan_rows} -> {after_plan_rows} "
        f"({'OK' if after_plan_rows >= before_plan_rows else 'WARN'})"
    )


if __name__ == "__main__":
    main()

