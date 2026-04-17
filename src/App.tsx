import React, { useEffect, useState } from "react";
import { AlertCircle, Calendar, CheckCircle2, Cloud, CloudRain, Star, Sun, Utensils, Wind } from "lucide-react";

type DashboardData = any;
const cls = (...s: string[]) => s.filter(Boolean).join(" ");

export default function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedWeekId, setSelectedWeekId] = useState("");
  const [selectedStoreId, setSelectedStoreId] = useState("");
  const [isEditingActions, setIsEditingActions] = useState(false);
  const [editedActions, setEditedActions] = useState<string[]>([]);

  const load = async (storeId?: string, weekId?: string) => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (storeId || selectedStoreId) qs.set("storeId", storeId ?? selectedStoreId);
      if (weekId || selectedWeekId) qs.set("weekId", weekId ?? selectedWeekId);
      const res = await fetch(`/api/dashboard-data?${qs.toString()}`);
      const d = await res.json();
      if (!res.ok) {
        setData(null);
        return;
      }
      setData(d);
      setSelectedStoreId(d.selectedStore?.id ?? "");
      const wk =
        d.selectedWeek?.id ??
        d.availableWeeks?.find((x: any) => x.range === d.weekRange)?.id ??
        d.availableWeeks?.[d.availableWeeks.length - 1]?.id ??
        "";
      setSelectedWeekId(wk);
      setEditedActions(d.summary?.actions ?? []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load().catch(() => setLoading(false));
  }, []);

  const handleSaveActions = async () => {
    await fetch("/api/save-actions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ storeId: selectedStoreId, weekId: selectedWeekId, actions: editedActions }),
    });
    await load(selectedStoreId, selectedWeekId);
    setIsEditingActions(false);
  };

  if (loading) return <div className="min-h-screen flex items-center justify-center dash-page">加载中...</div>;
  if (!data?.coreMetrics) return <div className="min-h-screen flex flex-col items-center justify-center gap-3 dash-page text-sm text-[var(--dash-muted)]">暂无看板数据。请确认 data 下门店 Excel 齐全后，访问 <code className="font-mono text-xs bg-white px-2 py-1 rounded border">/api/refresh-excel</code> 或带 <code className="font-mono text-xs">?refresh=1</code> 重新加载。</div>;

  return (
    <div className="min-h-screen pb-20 dash-page">
      <header className="dash-header px-6 py-[18px]">
        <div className="max-w-6xl mx-auto flex justify-between items-center gap-4">
          <div className="flex items-center gap-3">
            <div className="dash-logo-icon p-2 rounded-[10px]"><Utensils className="text-white" size={20} /></div>
            <div>
              <h1 className="dash-title text-[22px] leading-tight font-semibold tracking-tight">餐厅周度体检表</h1>
              <p className="text-[11px] text-[var(--dash-muted)] mt-0.5">当前门店：{data.selectedStore?.name}</p>
            </div>
          </div>
          <div className="flex gap-2">
            <select className="dash-select" value={selectedStoreId} onChange={(e) => load(e.target.value, "")}>{data.availableStores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
            <select className="dash-select" value={selectedWeekId} onChange={(e) => load(selectedStoreId, e.target.value)}>{data.availableWeeks.map((w: any) => <option key={w.id} value={w.id}>{w.range}</option>)}</select>
          </div>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-6 py-7 space-y-7">
        <section className="dash-card overflow-hidden"><h2 className="dash-section-head">一、核心经营指标</h2><table className="w-full text-sm"><thead><tr className="dash-table-head"><th className="px-4 py-2.5 text-left">指标</th><th className="px-4 py-2.5 text-right">本周值</th><th className="px-4 py-2.5 text-right">上周值</th><th className="px-4 py-2.5 text-right">环比变化</th><th className="px-4 py-2.5 text-left">健康参考</th><th className="px-4 py-2.5 text-center">状态</th></tr></thead><tbody>{data.coreMetrics.map((m: any, i: number) => <tr key={i} className="border-t border-[var(--dash-border)]"><td className="px-4 py-2.5">{m.label}</td><td className="px-4 py-2.5 text-right font-semibold dash-mono">{typeof m.thisWeek === "number" ? m.thisWeek.toLocaleString() : m.thisWeek}</td><td className="px-4 py-2.5 text-right dash-mono text-[var(--dash-muted)]">{typeof m.lastWeek === "number" ? m.lastWeek.toLocaleString() : m.lastWeek}</td><td className={cls("px-4 py-2.5 text-right font-semibold dash-mono", m.trend >= 0 ? "dash-trend-up" : "dash-trend-down")}>{m.trend > 0 ? "+" : ""}{m.trend}%</td><td className="px-4 py-2.5 text-[11px] text-[var(--dash-muted)]">{m.reference}</td><td className={cls("px-4 py-2.5 text-center text-[13px] font-semibold", m.statusColor)}>{m.statusText}</td></tr>)}</tbody></table></section>
        <section className="dash-card overflow-hidden"><h2 className="dash-section-head">二、菜品品类分析</h2><table className="w-full text-sm"><thead><tr className="dash-table-head"><th className="px-4 py-2.5 text-left">类目</th><th className="px-4 py-2.5 text-right">覆盖大类数</th><th className="px-4 py-2.5 text-right">本周销量</th><th className="px-4 py-2.5 text-right">销量占比</th><th className="px-4 py-2.5 text-right">本周销售额</th><th className="px-4 py-2.5 text-right">销售额占比</th><th className="px-4 py-2.5 text-right">环比销量变化</th><th className="px-4 py-2.5 text-center">状态</th></tr></thead><tbody>{data.categoryAnalysis.map((c: any, i: number) => <tr key={i} className="border-t border-[var(--dash-border)]"><td className="px-4 py-2.5">{c.name}</td><td className="px-4 py-2.5 text-right dash-mono">{typeof c.coveredMajorClassCount === "number" ? c.coveredMajorClassCount : "—"}</td><td className="px-4 py-2.5 text-right dash-mono">{c.sales}</td><td className="px-4 py-2.5 text-right dash-mono">{c.ratio}%</td><td className="px-4 py-2.5 text-right font-semibold dash-mono">¥{c.revenue.toLocaleString()}</td><td className="px-4 py-2.5 text-right dash-mono">{c.revRatio}%</td><td className={cls("px-4 py-2.5 text-right font-semibold dash-mono", c.trend >= 0 ? "dash-trend-up" : "dash-trend-down")}>{c.trend > 0 ? "+" : ""}{c.trend}%</td><td className={cls("px-4 py-2.5 text-center text-[13px] font-semibold", c.statusColor)}>{c.statusText}</td></tr>)}</tbody></table></section>
        <section className="space-y-4">
          <h2 className="dash-title text-[1.125rem] font-semibold">三、产品销售明细</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="dash-card p-4">
              <h3 className="font-semibold text-[15px] mb-2 flex items-center gap-2"><Star size={15} className="text-[var(--dash-accent)]" /> 销量 Top5 菜品</h3>
              {data.productDetails.topSales.map((p: any, i: number) => (
                <div key={i} className="flex justify-between text-[13px] py-1"><span>{i + 1}. {p.name}</span><span className="font-semibold dash-mono">{p.value} 份</span></div>
              ))}
            </div>
            <div className="dash-card p-4">
              <h3 className="font-semibold text-[15px] mb-2 flex items-center gap-2"><Utensils size={15} className="text-[var(--dash-accent)]" /> 销售额 Top5 菜品</h3>
              {data.productDetails.topRevenue.map((p: any, i: number) => (
                <div key={i} className="flex justify-between text-[13px] py-1"><span>{i + 1}. {p.name}</span><span className="font-semibold dash-mono">¥{p.value.toLocaleString()}</span></div>
              ))}
            </div>
            <div className="dash-card p-4">
              <h3 className="font-semibold text-[15px] mb-2 flex items-center gap-2"><AlertCircle size={15} className="text-[var(--dash-danger)]" /> 滞销 Bottom5 菜品</h3>
              {data.productDetails.bottomSales.map((p: any, i: number) => (
                <div key={i} className="py-1 text-[13px]"><div className="flex justify-between"><span>{i + 1}. {p.name}</span><span className="font-semibold dash-mono">{p.value} 份</span></div><div className="text-[11px] text-[var(--dash-danger)]">{p.note}</div></div>
              ))}
            </div>
          </div>
          <div className="dash-card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="dash-table-head">
                  <th className="px-4 py-2.5 text-left">指标</th>
                  <th className="px-4 py-2.5 text-left">内容</th>
                  <th className="px-4 py-2.5 text-left">环比变化</th>
                  <th className="px-4 py-2.5 text-left">健康参考</th>
                  <th className="px-4 py-2.5 text-center">状态</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-[var(--dash-border)]">
                  <td className="px-4 py-2.5">退菜/换菜数量</td>
                  <td className="px-4 py-2.5 font-semibold dash-mono">{data.productDetails.returns.count} 次</td>
                  <td className="px-4 py-2.5 dash-mono text-[var(--dash-muted)]">较上周 {data.productDetails.returns.lastCount} 次</td>
                  <td className="px-4 py-2.5 text-[11px] text-[var(--dash-muted)]">{data.productDetails.returns.reference}</td>
                  <td className={cls("px-4 py-2.5 text-center text-[13px] font-semibold", data.productDetails.returns.statusColor)}>{data.productDetails.returns.statusText}</td>
                </tr>
                <tr className="border-t border-[var(--dash-border)]">
                  <td className="px-4 py-2.5">菜品报损总金额（元）</td>
                  <td className="px-4 py-2.5 font-semibold dash-mono">¥{data.productDetails.lossAmount.amount.toLocaleString()}</td>
                  <td className={cls("px-4 py-2.5 font-semibold dash-mono", data.productDetails.lossAmount.trend >= 0 ? "dash-trend-down" : "dash-trend-up")}>
                    {data.productDetails.lossAmount.trend > 0 ? "+" : ""}{data.productDetails.lossAmount.trend}%
                  </td>
                  <td className="px-4 py-2.5 text-[11px] text-[var(--dash-muted)]">{data.productDetails.lossAmount.reference}</td>
                  <td className={cls("px-4 py-2.5 text-center text-[13px] font-semibold", data.productDetails.lossAmount.statusColor)}>{data.productDetails.lossAmount.statusText}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section className="dash-card overflow-hidden">
          <h2 className="dash-section-head">四、时段销售分析</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="dash-table-head">
                <th className="px-4 py-2.5 text-left">时段</th>
                <th className="px-4 py-2.5 text-right">订单数</th>
                <th className="px-4 py-2.5 text-right">占全天订单比</th>
                <th className="px-4 py-2.5 text-right">营收</th>
                <th className="px-4 py-2.5 text-right">占全天营收比</th>
                <th className="px-4 py-2.5 text-right">环比订单变化</th>
                <th className="px-4 py-2.5 text-right">估算翻台率</th>
                <th className="px-4 py-2.5 text-center">状态</th>
              </tr>
            </thead>
            <tbody>
              {data.timeAnalysis.table.map((t: any, i: number) => (
                <tr key={i} className="border-t border-[var(--dash-border)]">
                  <td className="px-4 py-2.5">{t.period}</td>
                  <td className="px-4 py-2.5 text-right dash-mono">{t.orders}</td>
                  <td className="px-4 py-2.5 text-right dash-mono">{t.ratio}%</td>
                  <td className="px-4 py-2.5 text-right font-semibold dash-mono">¥{t.revenue.toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-right dash-mono">{t.revRatio}%</td>
                  <td className={cls("px-4 py-2.5 text-right font-semibold dash-mono", t.trend >= 0 ? "dash-trend-up" : "dash-trend-down")}>{t.trend > 0 ? "+" : ""}{t.trend}%</td>
                  <td className="px-4 py-2.5 text-right dash-mono">{t.turnoverRate}</td>
                  <td className={cls("px-4 py-2.5 text-center text-[13px] font-semibold", t.statusColor)}>{t.statusText}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="p-4 dash-subpanel space-y-4">
            <div>
              <h4 className="text-[12px] font-semibold text-[var(--dash-accent)] mb-2 tracking-wide">本周时段异常汇总分析</h4>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {data.timeAnalysis.abnormalSummary.map((item: any, i: number) => (
                  <div key={i} className={cls("rounded-[var(--dash-radius-control)] border p-3", item.type === "high" ? "bg-[#e8f5e9] border-[#c8e6c9]" : "bg-[#fdecea] border-[#f5c6cb]")}>
                    <div className="text-[11px] font-semibold mb-1 text-[var(--dash-ink)]">{item.type === "high" ? "异常高" : "异常低"} · {item.day} · {item.period}</div>
                    <p className="text-[13px] leading-snug text-[var(--dash-ink)]">{item.reason}</p>
                  </div>
                ))}
              </div>
            </div>
            {data.timeAnalysis.lowestOrderDay && (
              <div className="rounded-[var(--dash-radius-control)] border border-[#ffe69c] bg-[#fff8e1] p-3">
                <div className="text-[13px] font-semibold text-[#856404] mb-1">周内订单最低日</div>
                <p className="text-[13px] leading-snug">{data.timeAnalysis.lowestOrderDay.day}（订单数: {data.timeAnalysis.lowestOrderDay.orders}），{data.timeAnalysis.lowestOrderDay.reason}</p>
              </div>
            )}
          </div>
        </section>
        <section className="dash-card overflow-hidden"><h2 className="dash-section-head">五、渠道与营销</h2><table className="w-full text-sm"><thead><tr className="dash-table-head"><th className="px-4 py-2.5 text-left">指标</th><th className="px-4 py-2.5 text-right">本周值</th><th className="px-4 py-2.5 text-right">上周值</th><th className="px-4 py-2.5 text-center">状态</th></tr></thead><tbody>{data.marketing.map((m: any, i: number) => <tr key={i} className="border-t border-[var(--dash-border)]"><td className="px-4 py-2.5">{m.label}</td><td className="px-4 py-2.5 text-right font-semibold dash-mono">{m.thisWeek}</td><td className="px-4 py-2.5 text-right dash-mono text-[var(--dash-muted)]">{m.lastWeek}</td><td className={cls("px-4 py-2.5 text-center text-[13px] font-semibold", m.statusColor)}>{m.statusText}</td></tr>)}</tbody></table></section>
        <section className="dash-card overflow-hidden">
          <h2 className="dash-section-head">六、服务与质量</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="dash-table-head">
                <th className="px-4 py-2.5 text-left">指标</th>
                <th className="px-4 py-2.5 text-right">本周值</th>
                <th className="px-4 py-2.5 text-right">上周值</th>
                <th className="px-4 py-2.5">健康参考</th>
                <th className="px-4 py-2.5 text-center">状态</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t border-[var(--dash-border)]">
                <td className="px-4 py-2.5">差评条数（店内评价·总分≤2）</td>
                <td className="px-4 py-2.5 text-right font-semibold dash-mono text-[var(--dash-danger)]">{data.service.negativeReviews.thisWeek} 条</td>
                <td className="px-4 py-2.5 text-right dash-mono text-[var(--dash-muted)]">{data.service.negativeReviews.lastWeek} 条</td>
                <td className="px-4 py-2.5 text-[11px] text-[var(--dash-muted)]">{data.service.negativeReviews.reference}</td>
                <td className={cls("px-4 py-2.5 text-center text-[13px] font-semibold", data.service.negativeReviews.statusColor)}>{data.service.negativeReviews.statusText}</td>
              </tr>
              <tr className="border-t border-[var(--dash-border)]">
                <td className="px-4 py-2.5 max-w-[14rem]">
                  <div className="font-medium leading-snug">{data.service.rating?.label ?? "店内评价均分（总分）"}</div>
                </td>
                <td className="px-4 py-2.5 text-right font-semibold dash-mono">{data.service.rating.thisWeek} 分</td>
                <td className="px-4 py-2.5 text-right dash-mono text-[var(--dash-muted)]">{data.service.rating.lastWeek} 分</td>
                <td className="px-4 py-2.5 text-[11px] text-[var(--dash-muted)]">{data.service.rating.reference}</td>
                <td className={cls("px-4 py-2.5 text-center text-[13px] font-semibold", data.service.rating.statusColor)}>{data.service.rating.statusText}</td>
              </tr>
            </tbody>
          </table>
          <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4 border-t border-[var(--dash-border)] bg-[#f8f9fa]">
            <div>
              <p className="text-[11px] font-semibold text-[var(--dash-muted)] mb-2">差评关键词 TOP3（按标点分句统计）</p>
              <div className="flex flex-wrap gap-2 min-w-0">
                {(data.service.badKeywords ?? []).map((k: string, i: number) => (
                  <div key={i} className="px-2.5 py-1.5 rounded-md text-[12px] font-medium leading-snug bg-[#fdecea] text-[var(--dash-danger)] border border-[#f5c6cb] whitespace-normal break-words">{k}</div>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[11px] font-semibold text-[var(--dash-muted)] mb-2">好评关键词 TOP3（按标点分句统计）</p>
              <div className="flex flex-wrap gap-2 min-w-0">
                {(data.service.goodKeywords ?? []).map((k: string, i: number) => (
                  <div key={i} className="px-2.5 py-1.5 rounded-md text-[12px] font-medium leading-snug bg-[#e8f5e9] text-[var(--dash-success)] border border-[#c8e6c9] whitespace-normal break-words">{k}</div>
                ))}
              </div>
            </div>
          </div>
        </section>
        <section className="space-y-4">
          <h2 className="dash-title text-[1.25rem] font-semibold">七、外部与环境</h2>
          <div className="dash-card overflow-hidden">
            <div className="px-4 py-2.5 border-b border-[var(--dash-border)] dash-table-head font-semibold flex items-center gap-2 text-[var(--dash-ink)]"><Calendar size={16} className="text-[var(--dash-accent)]" /> 节假日/特殊日期统计</div>
            <table className="w-full text-sm">
              <thead><tr className="dash-table-head"><th className="px-4 py-2.5 text-left">日期/类型</th><th className="px-4 py-2.5 text-right">天数</th><th className="px-4 py-2.5 text-right">总营收</th><th className="px-4 py-2.5 text-right">日均营收</th><th className="px-4 py-2.5 text-right">环比/平日增长</th><th className="px-4 py-2.5 text-center">状态</th></tr></thead>
              <tbody>{data.externalAndWeather.specialDates.map((h: any, i: number) => <tr key={i} className="border-t border-[var(--dash-border)]"><td className="px-4 py-2.5">{h.name}</td><td className="px-4 py-2.5 text-right dash-mono">{h.days}</td><td className="px-4 py-2.5 text-right font-semibold dash-mono">¥{h.revenue.toLocaleString()}</td><td className="px-4 py-2.5 text-right dash-mono">¥{h.avgDaily.toLocaleString()}</td><td className={cls("px-4 py-2.5 text-right font-semibold dash-mono", h.trend >= 0 ? "dash-trend-up" : "dash-trend-down")}>{h.trend > 0 ? "+" : ""}{h.trend}%</td><td className={cls("px-4 py-2.5 text-center text-[13px] font-semibold", h.statusColor)}>{h.statusText}</td></tr>)}</tbody>
            </table>
          </div>
          <div className="dash-card overflow-hidden">
            <div className="px-4 py-2.5 border-b border-[var(--dash-border)] dash-table-head font-semibold flex items-center gap-2 text-[var(--dash-ink)]"><CloudRain size={16} className="text-[var(--dash-accent)]" /> 异常天气影响分析</div>
            <table className="w-full text-sm">
              <thead><tr className="dash-table-head"><th className="px-4 py-2.5 text-left">日期</th><th className="px-4 py-2.5 min-w-[12rem]">北京天气预报（实况）</th><th className="px-4 py-2.5 text-right">营收</th><th className="px-4 py-2.5 text-right">订单数</th><th className="px-4 py-2.5 text-right">用餐人数</th><th className="px-4 py-2.5 text-right">支付用户数</th></tr></thead>
              <tbody>{data.externalAndWeather.weather.daily.map((w: any, i: number) => {
                const desc = String(w.description || w.type || "");
                const t = String(w.type || "");
                const icon = t.includes("雨雪") || t.includes("雨") ? <CloudRain size={13} className="text-[var(--dash-accent)] shrink-0" /> : t.includes("沙尘") ? <Cloud size={13} className="text-amber-800 shrink-0" /> : t.includes("大风") ? <Wind size={13} className="text-slate-600 shrink-0" /> : <Sun size={13} className="text-[#fd7e14] shrink-0" />;
                return (
                  <tr key={i} className="border-t border-[var(--dash-border)]">
                    <td className="px-4 py-2.5">{w.date}</td>
                    <td className="px-4 py-2.5"><div className="flex gap-2 items-start min-w-0"><span className="mt-0.5">{icon}</span><span className="text-[12px] leading-snug whitespace-normal break-words">{desc}</span></div></td>
                    <td className="px-4 py-2.5 text-right font-semibold dash-mono">¥{w.revenue.toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-right dash-mono">{w.orders}</td>
                    <td className="px-4 py-2.5 text-right dash-mono">{w.diners}</td>
                    <td className="px-4 py-2.5 text-right dash-mono">{w.paidUsers}</td>
                  </tr>
                );
              })}</tbody>
            </table>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 border-t border-[var(--dash-border)] bg-[#f8f9fa] text-[13px]">
              <div>
                <div className="flex justify-between gap-2"><span className="text-[var(--dash-muted)]">本周异常天气天数：</span><span className="font-semibold dash-mono">{data.externalAndWeather.weather.summary.abnormalDays} 天</span></div>
                <div className="flex justify-between mt-1 gap-2"><span className="text-[var(--dash-muted)]">异常天气日均营收：</span><span className="font-semibold dash-mono">¥{data.externalAndWeather.weather.summary.abnormalAvgRev.toLocaleString()}</span></div>
              </div>
              <div>
                <div className="flex justify-between gap-2"><span className="text-[var(--dash-muted)]">正常天气日均营收：</span><span className="font-semibold dash-mono">¥{data.externalAndWeather.weather.summary.normalAvgRev.toLocaleString()}</span></div>
                <div className="flex justify-between mt-1 gap-2"><span className="text-[var(--dash-muted)] shrink">异常天气是否导致营收下降超过30%？</span><span className="font-semibold text-[var(--dash-danger)] text-right">{data.externalAndWeather.weather.summary.isImpacted}</span></div>
              </div>
            </div>
          </div>
        </section>
        <section className="dash-card p-5"><div className="flex justify-between items-center mb-4 gap-3"><h2 className="dash-title text-[1.35rem] font-semibold flex items-center gap-2"><CheckCircle2 size={20} className="text-[var(--dash-accent)]" /> 综合结论与下周行动</h2><button type="button" className="dash-btn-ghost shrink-0" onClick={() => setIsEditingActions((v) => !v)}>{isEditingActions ? "取消编辑" : "人工填写行动计划"}</button></div><div className="grid grid-cols-1 lg:grid-cols-2 gap-5"><div className="border border-[var(--dash-border)] rounded-[var(--dash-radius-card)] p-4 bg-white"><p className="text-[12px] text-[var(--dash-success)] font-semibold mb-2">本周核心亮点</p><p className="text-[13px] leading-relaxed">{data.summary.highlight}</p><p className="text-[12px] text-[var(--dash-danger)] font-semibold mt-5 mb-2">本周核心问题</p><p className="text-[13px] leading-relaxed">{data.summary.problem}</p></div><div className="dash-panel-accent p-4"><p className="text-[13px] font-semibold text-[var(--dash-accent)] mb-3">下周重点行动计划（不超过3条）</p>{(isEditingActions ? editedActions : data.summary.actions).map((a: string, i: number) => <div key={i} className="flex gap-3 mb-3"><div className="w-7 h-7 rounded-[6px] bg-[var(--dash-accent)] text-white text-[12px] font-semibold flex items-center justify-center shrink-0">{i + 1}</div>{isEditingActions ? <textarea className="flex-1 border border-[var(--dash-border)] rounded-[var(--dash-radius-control)] p-2 text-[13px] h-20 font-sans" value={a} onChange={(e) => { const n = [...editedActions]; n[i] = e.target.value; setEditedActions(n); }} /> : <p className="text-[13px] pt-1 leading-relaxed">{a}</p>}</div>)}{isEditingActions && editedActions.length < 3 && <button type="button" className="dash-btn-dashed mb-2" onClick={() => setEditedActions([...editedActions, ""])}>+ 添加行动项</button>}{isEditingActions && <button type="button" className="dash-btn-primary" onClick={handleSaveActions}>保存记录</button>}</div></div></section>
      </main>
    </div>
  );
}
