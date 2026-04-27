from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _auto_recompute_from_week_id(payload: dict) -> str:
    """
    默认增量周更边界：
    - 读取现有 ui_payload 的最大 week_id
    - 自动取下一周（+7天）作为 recompute 起点
    这样默认只会追加新周，不会重算已生成历史周。
    """
    max_wk: str | None = None
    stores = payload.get("stores", {})
    for _sid, sv in stores.items():
        weeks = (sv or {}).get("weeks", {})
        for wk in (weeks or {}).keys():
            w = str(wk)
            if max_wk is None or w > max_wk:
                max_wk = w
    if not max_wk:
        return "2026-04-06"
    dt = datetime.strptime(max_wk, "%Y-%m-%d").date()
    return (dt + timedelta(days=7)).isoformat()


def _check_negative_keyword_consistency(payload: dict) -> list[str]:
    issues: list[str] = []
    stores = payload.get("stores", {})
    for sid, sv in stores.items():
        weeks = (sv or {}).get("weeks", {})
        for wk, wv in weeks.items():
            service = (wv or {}).get("service", {})
            neg = ((service.get("negativeReviews") or {}).get("thisWeek") or 0)
            bad = service.get("badKeywords") or []
            if neg == 0 and bad:
                issues.append(f"{sid} {wk}: 差评条数=0 但 badKeywords 非空")
            if neg > 0 and not bad:
                issues.append(f"{sid} {wk}: 差评条数>0 但 badKeywords 为空")
    return issues


def _check_returns_nonzero(payload: dict, check_weeks: list[str]) -> list[str]:
    warnings: list[str] = []
    stores = payload.get("stores", {})
    for sid, sv in stores.items():
        weeks = (sv or {}).get("weeks", {})
        vals: list[int] = []
        for wk in check_weeks:
            returns = (((weeks.get(wk) or {}).get("productDetails") or {}).get("returns") or {})
            vals.append(int(returns.get("count") or 0))
        if vals and sum(vals) == 0:
            warnings.append(f"{sid}: 指定周退/换菜数量全为0 -> {dict(zip(check_weeks, vals))}")
    return warnings


def _print_snapshot(payload: dict, weeks: list[str]) -> None:
    stores = payload.get("stores", {})
    print("\n[快照] 服务评分与退/换菜")
    for sid in sorted(stores.keys()):
        print(f"\n- {sid}")
        sv = stores[sid]
        wmap = (sv or {}).get("weeks", {})
        for wk in weeks:
            w = wmap.get(wk) or {}
            rating = ((w.get("service") or {}).get("rating") or {}).get("thisWeek")
            ret = (((w.get("productDetails") or {}).get("returns") or {}).get("count") or 0)
            print(f"  {wk} | 评分={rating} | 退/换菜={ret}")


def main() -> int:
    parser = argparse.ArgumentParser(description="One-command Monday update: rebuild + validate + next steps.")
    parser.add_argument(
        "--recompute-from",
        default="auto",
        help="week_id 边界。默认 auto=从当前 payload 最后一周的下一周开始（仅追加新周）。",
    )
    parser.add_argument("--strict", action="store_true", help="存在一致性问题时返回非0")
    args = parser.parse_args()

    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from core.dashboard_builder import write_ui_payload
    from core.paths import ui_payload_path

    payload_path = Path(ui_payload_path())
    current_payload = _load_payload(payload_path) if payload_path.exists() else {"stores": {}}
    recompute_from = (
        _auto_recompute_from_week_id(current_payload)
        if str(args.recompute_from).strip().lower() == "auto"
        else str(args.recompute_from).strip()
    )

    print(f"[1/3] 重建 ui_payload（recompute_from_week_id={recompute_from}）...")
    out = write_ui_payload(auto_persist_metrics=True, recompute_from_week_id=recompute_from)
    payload = _load_payload(Path(ui_payload_path()))
    print(f"[ok] payload: {out}")

    # 固定检查窗口：历史交接段 + 新数据段
    check_weeks = ["2026-03-16", "2026-03-23", "2026-03-30", "2026-04-06", "2026-04-13"]

    print("[2/3] 运行一致性检查...")
    issues = _check_negative_keyword_consistency(payload)
    return_warnings = _check_returns_nonzero(payload, check_weeks)

    _print_snapshot(payload, check_weeks)

    if issues:
        print("\n[问题] 差评条数与关键词不一致：")
        for item in issues[:50]:
            print(f"  - {item}")
    else:
        print("\n[ok] 差评条数与关键词一致性通过")

    if return_warnings:
        print("\n[警告] 退/换菜检查：")
        for item in return_warnings:
            print(f"  - {item}")
    else:
        print("\n[ok] 退/换菜检查通过（非全0）")

    print("\n[3/3] 下一步命令（复制执行）")
    print(
        "git add core/dashboard_builder.py core/metrics_engine.py ingestion/pipeline.py "
        "data/warehouse/ui_payload.json data/warehouse/weekly_metrics.json "
        "docs/看板数据处理与页面展示全链路说明.md docs/每周一数据更新标准操作手册.md scripts/run_monday_update.py"
    )
    print('git commit -m "weekly update"')
    print("git push origin main")

    if args.strict and (issues or return_warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

