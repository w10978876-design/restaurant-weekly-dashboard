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


def _inject_style() -> None:
    st.markdown(
        """
<style>
@import url("https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap");
:root{
  --dash-bg: #f8f9fa;
  --dash-surface: #ffffff;
  --dash-ink: #1a1a1a;
  --dash-muted: #6c757d;
  --dash-border: #e9ecef;
  --dash-accent: #0066ff;
  --dash-accent-soft: #e8f1ff;
  --dash-success: #28a745;
  --dash-danger: #dc3545;
  --dash-radius-card: 10px;
  --dash-radius-control: 8px;
  --dash-shadow-card: 0 1px 2px rgba(26, 26, 26, 0.04), 0 1px 3px rgba(26, 26, 26, 0.06);
}
.stApp, body {
  background: var(--dash-bg);
  color: var(--dash-ink);
  font-family: "Inter", ui-sans-serif, system-ui, sans-serif;
}
section.main > div.block-container {
  max-width: 1152px;
  padding-top: 0.7rem;
  padding-bottom: 1.8rem;
}
#MainMenu, header[data-testid="stHeader"], footer {visibility: hidden;}
.dash-wrap {padding-top: 0.15rem;}
.dash-head{
  display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px;
  background: var(--dash-surface);
  border:1px solid var(--dash-border);border-radius:var(--dash-radius-card);padding:14px 16px;
  box-shadow: var(--dash-shadow-card);
}
.dash-head h2{
  margin:0;
  color:var(--dash-ink);
  font-family: "Playfair Display", Georgia, "Times New Roman", serif;
  font-size:22px;
  line-height:1.1;
  font-weight:600;
  letter-spacing:-0.01em;
}
.dash-card {
  border:1px solid var(--dash-border);border-radius:var(--dash-radius-card);padding:14px;background:var(--dash-surface);
  box-shadow: var(--dash-shadow-card);
}
.dash-kpi {
  border:1px solid var(--dash-border);border-radius:var(--dash-radius-control);padding:10px 12px;background:var(--dash-surface);
}
.dash-muted {color:var(--dash-muted);font-size:11px}
.dash-title {font-weight:700;color:var(--dash-ink)}
.dash-chip-good {background:#e8f5e9;border:1px solid #c8e6c9;color:#1f7a34;border-radius:6px;padding:4px 9px;font-size:12px;display:inline-block;margin:2px;}
.dash-chip-bad {background:#fdecea;border:1px solid #f5c6cb;color:#b42318;border-radius:6px;padding:4px 9px;font-size:12px;display:inline-block;margin:2px;}
.dash-subtitle {
  font-size:13px; font-weight:600; color:#334155; margin:2px 0 8px;
}
h3 {
  color:var(--dash-ink) !important;
  font-family: "Playfair Display", Georgia, "Times New Roman", serif !important;
  font-size: 1.125rem !important;
  margin-top: 12px !important;
  border-left:none;
  padding-left:0;
}
div[data-testid="stDataFrame"] {
  border:1px solid var(--dash-border);
  border-radius:var(--dash-radius-card);
  overflow:hidden;
  box-shadow: var(--dash-shadow-card);
}
div[data-testid="stDataFrame"] [role="columnheader"] {
  background: #f1f3f5 !important;
  color: var(--dash-muted) !important;
  font-size: 12px !important;
  font-weight: 600 !important;
}
div[data-testid="stDataFrame"] [role="gridcell"] {
  font-size: 13px !important;
  color: var(--dash-ink) !important;
}
div[data-testid="stMetric"] {
  border:1px solid var(--dash-border);
  border-radius:var(--dash-radius-control);
  padding:6px 10px;
  background:var(--dash-surface);
}
div[data-testid="stMetricLabel"] {
  font-size: 11px !important;
  color: var(--dash-muted) !important;
}
div[data-testid="stMetricValue"] {
  font-size: 18px !important;
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace !important;
}
[data-testid="stSidebar"] * {
  font-size: 13px !important;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _show_kpi_cards(core: list[dict[str, Any]]) -> None:
    cols = st.columns(len(core) if core else 1)
    for i, m in enumerate(core):
        with cols[i]:
            st.markdown('<div class="dash-kpi">', unsafe_allow_html=True)
            st.markdown(f"**{m.get('label','')}**")
            st.markdown(f"<div class='dash-title' style='font-size:22px'>{_fmt_num(m.get('thisWeek',''))}</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='dash-muted'>上周 {_fmt_num(m.get('lastWeek',''))} ｜ 环比 {m.get('trend',0)}%</div>",
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)


def _show_table(title: str, rows: list[dict[str, Any]]) -> None:
    st.markdown(f"<div class='dash-subtitle'>{title}</div>", unsafe_allow_html=True)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("暂无数据")


def main() -> None:
    st.set_page_config(page_title="餐厅周度经营看板", layout="wide")
    _inject_style()
    st.markdown('<div class="dash-wrap">', unsafe_allow_html=True)

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

    st.markdown(
        f"<div class='dash-head'><h2>餐厅周度体检表</h2><div class='dash-muted'>门店：{store_id} ｜ 周：{week_id} ｜ {week.get('weekRange','')}</div></div>",
        unsafe_allow_html=True,
    )

    # 一、核心经营指标
    st.markdown("### 一、核心经营指标")
    core = week.get("coreMetrics", [])
    if core:
        _show_kpi_cards(core)

    # 二、菜品品类分析
    st.markdown("### 二、菜品品类分析")
    _show_table("菜品品类明细", week.get("categoryAnalysis", []))

    # 三、产品销售明细
    st.markdown("### 三、产品销售明细")
    pdetail = week.get("productDetails", {})
    ctop1, ctop2, ctop3 = st.columns(3)
    with ctop1:
        st.markdown("<div class='dash-card'><div class='dash-subtitle'>销量 Top5 菜品</div>", unsafe_allow_html=True)
        for i, x in enumerate(pdetail.get("topSales", []), 1):
            st.write(f"{i}. {x.get('name','')} - {x.get('value','')} 份")
        st.markdown("</div>", unsafe_allow_html=True)
    with ctop2:
        st.markdown("<div class='dash-card'><div class='dash-subtitle'>销售额 Top5 菜品</div>", unsafe_allow_html=True)
        for i, x in enumerate(pdetail.get("topRevenue", []), 1):
            st.write(f"{i}. {x.get('name','')} - ¥{_fmt_num(x.get('value',0))}")
        st.markdown("</div>", unsafe_allow_html=True)
    with ctop3:
        st.markdown("<div class='dash-card'><div class='dash-subtitle'>滞销 Bottom5 菜品</div>", unsafe_allow_html=True)
        for i, x in enumerate(pdetail.get("bottomSales", []), 1):
            st.write(f"{i}. {x.get('name','')} - {x.get('value','')} 份")
            if x.get("note"):
                st.caption(x.get("note"))
        st.markdown("</div>", unsafe_allow_html=True)
    rc, lc = st.columns(2)
    with rc:
        r = pdetail.get("returns", {})
        st.markdown(f"**退菜/换菜**：{r.get('count','-')} 次（上周 {r.get('lastCount','-')}）")
    with lc:
        l = pdetail.get("lossAmount", {})
        st.markdown(f"**报损金额**：¥{_fmt_num(l.get('amount',0))}（环比 {l.get('trend',0)}%）")

    # 四、时段销售分析
    st.markdown("### 四、时段销售分析")
    t = week.get("timeAnalysis", {})
    _show_table("时段销售表", t.get("table", []))
    abn = t.get("abnormalSummary", [])
    if abn:
        st.markdown("**本周时段异常汇总**")
        for x in abn:
            st.write(f"- {x.get('type','')}｜{x.get('day','')}｜{x.get('period','')}：{x.get('reason','')}")
    else:
        st.caption("本周无异常时段命中")
    if t.get("lowestOrderDay"):
        low = t["lowestOrderDay"]
        st.warning(f"周内订单最低日：{low.get('day','')}（{low.get('orders','')}单）{low.get('reason','')}")

    # 五、渠道与营销
    st.markdown("### 五、渠道与营销")
    _show_table("渠道与营销指标", week.get("marketing", []))

    # 六、服务与质量
    st.markdown("### 六、服务与质量")
    service = week.get("service", {})
    nrv = service.get("negativeReviews", {})
    rat = service.get("rating", {})
    cqa1, cqa2 = st.columns(2)
    with cqa1:
        st.markdown(f"**差评条数（总分≤2）**：{nrv.get('thisWeek','-')}（上周 {nrv.get('lastWeek','-')}）")
    with cqa2:
        st.markdown(f"**门店评分**：{rat.get('thisWeek','-')}（上周 {rat.get('lastWeek','-')}）")
    ckg, ckb = st.columns(2)
    with ckg:
        st.markdown("**好评关键词 TOP3**")
        gks = service.get("goodKeywords", [])
        if not gks:
            st.caption("本周暂无命中")
        for k in gks:
            st.markdown(f"<span class='dash-chip-good'>{k}</span>", unsafe_allow_html=True)
    with ckb:
        st.markdown("**差评关键词 TOP3**")
        bks = service.get("badKeywords", [])
        if not bks:
            st.caption("本周暂无命中")
        for k in bks:
            st.markdown(f"<span class='dash-chip-bad'>{k}</span>", unsafe_allow_html=True)
    with st.expander("查看关键词证据句（核验）", expanded=False):
        st.markdown("**好评证据**")
        for row in service.get("goodKeywordEvidence", []):
            st.caption(f"- {row.get('keyword','')}：{' / '.join(row.get('sentences', []))}")
        st.markdown("**差评证据**")
        for row in service.get("badKeywordEvidence", []):
            st.caption(f"- {row.get('keyword','')}：{' / '.join(row.get('sentences', []))}")

    # 七、外部与环境
    st.markdown("### 七、外部与环境")
    ext = week.get("externalAndWeather", {})
    _show_table("节假日/特殊日期统计", ext.get("specialDates", []))
    weather = ext.get("weather", {})
    _show_table("异常天气影响分析（日明细）", weather.get("daily", []))
    if weather.get("summary"):
        s = weather.get("summary", {})
        wc1, wc2, wc3, wc4 = st.columns(4)
        with wc1:
            st.metric("异常天气天数", f"{s.get('abnormalDays', '-')}")
        with wc2:
            st.metric("异常天气日均营收", f"¥{_fmt_num(s.get('abnormalAvgRev', 0))}")
        with wc3:
            st.metric("正常天气日均营收", f"¥{_fmt_num(s.get('normalAvgRev', 0))}")
        with wc4:
            st.metric("天气是否显著影响", str(s.get("isImpacted", "-")))
    else:
        st.caption("天气汇总暂无数据")

    # 八、综合结论与下周行动
    st.markdown("### 八、综合结论与下周行动")
    summary = _merge_actions(week.get("summary", {}), store_id, week_id)
    hc1, hc2 = st.columns(2)
    with hc1:
        st.markdown("<div class='dash-card'><div class='dash-subtitle'>本周核心亮点</div>", unsafe_allow_html=True)
        st.write(summary.get("highlight", ""))
        st.markdown("</div>", unsafe_allow_html=True)
    with hc2:
        st.markdown("<div class='dash-card'><div class='dash-subtitle'>本周核心问题</div>", unsafe_allow_html=True)
        st.write(summary.get("problem", ""))
        st.markdown("</div>", unsafe_allow_html=True)

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
    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()

