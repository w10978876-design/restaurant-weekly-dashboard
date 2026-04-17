from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import streamlit as st

from core.dashboard_builder import write_ui_payload
from core.paths import action_plans_path, ui_payload_path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_payload() -> dict[str, Any]:
    p = Path(ui_payload_path())
    if not p.exists():
        write_ui_payload()
    raw = p.read_text(encoding="utf-8")
    return json.loads(raw.replace("NaN", "null"))


def _get_github_cfg() -> dict[str, str] | None:
    try:
        token = str(st.secrets.get("GITHUB_TOKEN", "")).strip()
        owner = str(st.secrets.get("GITHUB_REPO_OWNER", "")).strip()
        repo = str(st.secrets.get("GITHUB_REPO_NAME", "")).strip()
        branch = str(st.secrets.get("GITHUB_BRANCH", "main")).strip() or "main"
    except Exception:
        return None
    if not token or not owner or not repo:
        return None
    return {"token": token, "owner": owner, "repo": repo, "branch": branch}


def _github_get_json(cfg: dict[str, str], repo_path: str) -> tuple[dict[str, Any] | None, str | None]:
    url = f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}/contents/{repo_path}"
    headers = {"Authorization": f"Bearer {cfg['token']}", "Accept": "application/vnd.github+json"}
    r = requests.get(url, headers=headers, params={"ref": cfg["branch"]}, timeout=20)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    data = r.json()
    content = data.get("content", "")
    text = base64.b64decode(content).decode("utf-8") if content else "{}"
    return json.loads(text), data.get("sha")


def _github_put_json(cfg: dict[str, str], repo_path: str, payload: dict[str, Any], sha: str | None) -> None:
    url = f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}/contents/{repo_path}"
    headers = {"Authorization": f"Bearer {cfg['token']}", "Accept": "application/vnd.github+json"}
    body: dict[str, Any] = {
        "message": f"update {repo_path} at {_now_iso()}",
        "content": base64.b64encode(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")).decode("utf-8"),
        "branch": cfg["branch"],
    }
    if sha:
        body["sha"] = sha
    r = requests.put(url, headers=headers, json=body, timeout=20)
    r.raise_for_status()


def _load_action_items() -> list[dict[str, Any]]:
    cfg = _get_github_cfg()
    repo_path = "data/warehouse/action_plans.json"
    if cfg:
        try:
            payload, _ = _github_get_json(cfg, repo_path)
            if payload and isinstance(payload.get("items"), list):
                return payload["items"]
        except Exception:
            pass
    p = Path(action_plans_path())
    if not p.exists():
        return []
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        return payload.get("items", []) if isinstance(payload.get("items"), list) else []
    except Exception:
        return []


def _save_action_items(items: list[dict[str, Any]]) -> None:
    payload = {"version": 1, "saved_at": _now_iso(), "items": items}
    p = Path(action_plans_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cfg = _get_github_cfg()
    if not cfg:
        return
    repo_path = "data/warehouse/action_plans.json"
    remote_payload, sha = _github_get_json(cfg, repo_path)
    # 远端存在时，用最新本地覆盖（本地已承载当前编辑意图）
    _github_put_json(cfg, repo_path, payload, sha)


def _merge_actions(base_summary: dict[str, Any], store_id: str, week_id: str) -> dict[str, Any]:
    items = _load_action_items()
    actions = [str(x.get("detail", "")).strip() for x in items if x.get("store_id") == store_id and x.get("week_id") == week_id]
    out = dict(base_summary or {})
    out["actions"] = [x for x in actions if x] if actions else list(out.get("actions", []))
    return out


def _save_actions_for_week(store_id: str, week_id: str, actions: list[str]) -> None:
    actions = [x.strip() for x in actions if x and x.strip()][:3]
    all_items = _load_action_items()
    all_items = [x for x in all_items if not (x.get("store_id") == store_id and x.get("week_id") == week_id)]
    stamp = _now_iso()
    new_rows = [
        {
            "id": f"{store_id}-{week_id}-{i+1}-{int(datetime.now().timestamp())}",
            "store_id": store_id,
            "week_id": week_id,
            "title": f"行动{i+1}",
            "detail": detail,
            "status": "待办",
            "created_at": stamp,
            "updated_at": stamp,
        }
        for i, detail in enumerate(actions)
    ]
    _save_action_items(all_items + new_rows)


def _fmt_num(v: Any) -> str:
    if isinstance(v, (int, float)):
        if abs(float(v)) >= 1000:
            return f"{float(v):,.0f}"
        return f"{float(v):,.2f}"
    return str(v)


def main() -> None:
    st.set_page_config(page_title="餐厅周度经营看板", layout="wide")
    st.title("餐厅周度经营看板")

    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("重建最新数据"):
            write_ui_payload()
            st.success("已重建 ui_payload.json")
    with c2:
        st.caption("如配置了 GitHub Secrets，行动计划会自动写回仓库，供团队共享。")

    payload = _load_payload()
    stores = payload.get("stores", {})
    if not stores:
        st.warning("暂无门店数据。")
        return

    store_ids = sorted(stores.keys())
    store_id = st.sidebar.selectbox("门店", store_ids, index=0)
    weeks_map = stores[store_id].get("weeks", {})
    week_ids = sorted(weeks_map.keys())
    week_id = st.sidebar.selectbox("周", week_ids, index=max(len(week_ids) - 1, 0))
    week = weeks_map[week_id]

    st.subheader(f"{store_id} · {week_id} · {week.get('weekRange', '')}")

    # Core metrics
    core = week.get("coreMetrics", [])
    if core:
        cols = st.columns(len(core))
        for i, m in enumerate(core):
            with cols[i]:
                st.metric(
                    label=str(m.get("label", "")),
                    value=_fmt_num(m.get("thisWeek", "")),
                    delta=f"{_fmt_num(m.get('trend', 0))}%",
                )

    # Summary
    summary = _merge_actions(week.get("summary", {}), store_id, week_id)
    st.markdown("### 本周核心亮点")
    st.write(summary.get("highlight", ""))
    st.markdown("### 本周核心问题")
    st.write(summary.get("problem", ""))

    # Service keywords + evidence
    service = week.get("service", {})
    colg, colb = st.columns(2)
    with colg:
        st.markdown("### 好评关键词")
        st.write("；".join(service.get("goodKeywords", [])) or "无")
        for row in service.get("goodKeywordEvidence", []):
            st.caption(f"- {row.get('keyword', '')}: {' / '.join(row.get('sentences', []))}")
    with colb:
        st.markdown("### 差评关键词")
        st.write("；".join(service.get("badKeywords", [])) or "无")
        for row in service.get("badKeywordEvidence", []):
            st.caption(f"- {row.get('keyword', '')}: {' / '.join(row.get('sentences', []))}")

    # Tables
    st.markdown("### 时段分析")
    st.dataframe(week.get("timeAnalysis", {}).get("table", []), use_container_width=True)
    st.markdown("### 品类分析")
    st.dataframe(week.get("categoryAnalysis", []), use_container_width=True)

    # Actions editor
    st.markdown("### 本周行动计划（最多3条）")
    current_actions = list(summary.get("actions", []))[:3]
    while len(current_actions) < 3:
        current_actions.append("")
    a1 = st.text_area("行动1", value=current_actions[0], key=f"a1-{store_id}-{week_id}")
    a2 = st.text_area("行动2", value=current_actions[1], key=f"a2-{store_id}-{week_id}")
    a3 = st.text_area("行动3", value=current_actions[2], key=f"a3-{store_id}-{week_id}")
    if st.button("保存行动计划", type="primary"):
        try:
            _save_actions_for_week(store_id, week_id, [a1, a2, a3])
            st.success("已保存。")
        except Exception as exc:
            st.error(f"保存失败：{exc}")


if __name__ == "__main__":
    main()

