import express from "express";
import { createServer as createViteServer } from "vite";
import fs from "fs";
import path from "path";
import { spawnSync } from "child_process";

const ROOT = process.cwd();
const UI_PAYLOAD_PATH = path.join(ROOT, "data", "warehouse", "ui_payload.json");
const ACTIONS_PATH = path.join(ROOT, "data", "warehouse", "action_plans.json");

type ActionPlanRow = {
  id: string;
  store_id: string;
  week_id: string;
  title: string;
  detail: string;
  status: string;
  created_at: string;
  updated_at: string;
};

const nowIso = () => new Date().toISOString();

function ensureActionStore() {
  if (fs.existsSync(ACTIONS_PATH)) return;
  fs.mkdirSync(path.dirname(ACTIONS_PATH), { recursive: true });
  fs.writeFileSync(
    ACTIONS_PATH,
    JSON.stringify({ version: 1, saved_at: nowIso(), items: [] }, null, 2),
    "utf-8"
  );
}

function readActionPlans(): ActionPlanRow[] {
  ensureActionStore();
  const raw = JSON.parse(fs.readFileSync(ACTIONS_PATH, "utf-8")) as { items?: unknown[] };
  const items = Array.isArray(raw?.items) ? raw.items : [];
  return items.map((it) => {
    const r = it as Record<string, unknown>;
    return {
      id: String(r.id ?? ""),
      store_id: String(r.store_id ?? ""),
      week_id: String(r.week_id ?? ""),
      title: String(r.title ?? ""),
      detail: String(r.detail ?? ""),
      status: String(r.status ?? "待办"),
      created_at: String(r.created_at ?? nowIso()),
      updated_at: String(r.updated_at ?? nowIso()),
    };
  });
}

function saveActionPlans(items: ActionPlanRow[]) {
  fs.mkdirSync(path.dirname(ACTIONS_PATH), { recursive: true });
  fs.writeFileSync(
    ACTIONS_PATH,
    JSON.stringify({ version: 1, saved_at: nowIso(), items }, null, 2),
    "utf-8"
  );
}

function refreshUiPayloadFromExcel(): { ok: boolean; error: string } {
  const r = spawnSync("python3", ["-m", "core.dashboard_builder"], {
    cwd: ROOT,
    env: { ...process.env, PYTHONPATH: ROOT },
    encoding: "utf-8",
    maxBuffer: 50 * 1024 * 1024,
    timeout: 180000,
  });
  if (r.status !== 0) {
    console.error("core.dashboard_builder failed:", r.stderr || r.stdout);
    return { ok: false, error: r.stderr || r.stdout || "unknown" };
  }
  return { ok: true, error: "" };
}

function readUiPayload(): Record<string, unknown> | null {
  if (!fs.existsSync(UI_PAYLOAD_PATH)) return null;
  const raw = fs.readFileSync(UI_PAYLOAD_PATH, "utf-8");
  return JSON.parse(raw.replace(/\bNaN\b/g, "null")) as Record<string, unknown>;
}

function mergeActionsIntoPayload(
  payload: Record<string, unknown>,
  storeId: string,
  weekId: string
): Record<string, unknown> {
  const saved = readActionPlans()
    .filter((it) => it.store_id === storeId && it.week_id === weekId)
    .sort((a, b) => a.updated_at.localeCompare(b.updated_at))
    .map((it) => it.detail)
    .filter(Boolean);
  const next = { ...payload };
  const summary = (typeof next.summary === "object" && next.summary) ? { ...(next.summary as object) } : {};
  next.summary = {
    ...summary,
    actions: saved.length ? saved : ((summary as Record<string, unknown>).actions as string[]) || [],
  };
  return next;
}

async function startServer() {
  const app = express();
  const PORT = Number(process.env.PORT || 3010);
  app.use(express.json());

  app.get("/api/health", (_req, res) => {
    res.json({ status: "ok", timestamp: nowIso() });
  });

  app.post("/api/refresh-excel", (_req, res) => {
    const r = refreshUiPayloadFromExcel();
    if (!r.ok) {
      res.status(500).json({ success: false, message: r.error });
      return;
    }
    res.json({ success: true, message: "已从 Excel 重新生成 ui_payload.json" });
  });

  app.get("/api/dashboard-data", (req, res) => {
    const needRefresh = req.query.refresh === "1" || !fs.existsSync(UI_PAYLOAD_PATH);
    if (needRefresh) {
      const r = refreshUiPayloadFromExcel();
      if (!r.ok) {
        res.status(500).json({
          error: "无法从 Excel 生成看板数据",
          detail: r.error,
          availableStores: [],
          availableWeeks: [],
        });
        return;
      }
    }

    const bundle = readUiPayload();
    const stores = bundle?.stores as Record<string, { weeks?: Record<string, unknown> }> | undefined;
    if (!stores || typeof stores !== "object") {
      res.status(200).json({
        availableStores: [],
        availableWeeks: [],
        selectedStore: null,
        selectedWeek: null,
        coreMetrics: [],
        summary: { highlight: "", problem: "", actions: [] },
      });
      return;
    }

    const storeIds = Object.keys(stores)
      .filter((k) => stores[k]?.weeks && Object.keys(stores[k].weeks!).length)
      .sort();
    if (!storeIds.length) {
      res.status(200).json({
        availableStores: [],
        availableWeeks: [],
        selectedStore: null,
        selectedWeek: null,
        coreMetrics: [],
        summary: { highlight: "", problem: "", actions: [] },
      });
      return;
    }

    const requestedStore = String(req.query.storeId ?? storeIds[0]);
    const storeId = storeIds.includes(requestedStore) ? requestedStore : storeIds[0];
    const weeksMap = stores[storeId].weeks || {};
    const weekIds = Object.keys(weeksMap).sort();
    const requestedWeek = String(req.query.weekId ?? weekIds[weekIds.length - 1]);
    const weekId = weekIds.includes(requestedWeek) ? requestedWeek : weekIds[weekIds.length - 1];
    const base = weeksMap[weekId] as Record<string, unknown> | undefined;
    if (!base) {
      res.status(404).json({ error: "week not found" });
      return;
    }

    const merged = mergeActionsIntoPayload(base, storeId, weekId);
    const weekRow = weeksMap[weekId] as Record<string, unknown>;

    res.json({
      weekRange: merged.weekRange,
      availableStores: storeIds.map((id) => ({ id, name: id })),
      availableWeeks: weekIds.map((id) => ({
        id,
        range: (weeksMap[id] as Record<string, unknown>)?.weekRange ?? id,
      })),
      selectedStore: { id: storeId, name: storeId },
      selectedWeek: { id: weekId, range: weekRow?.weekRange },
      coreMetrics: merged.coreMetrics,
      categoryAnalysis: merged.categoryAnalysis,
      productDetails: merged.productDetails,
      timeAnalysis: merged.timeAnalysis,
      marketing: merged.marketing,
      service: merged.service,
      externalAndWeather: merged.externalAndWeather,
      summary: merged.summary,
      trendData: merged.trendData,
      weeklyTable: merged.weeklyTable,
      generatedAt: bundle.generated_at,
    });
  });

  const saveHandler = (req: express.Request, res: express.Response) => {
    const storeId = String(req.body?.storeId ?? "");
    const weekId = String(req.body?.weekId ?? "");
    const actions = Array.isArray(req.body?.actions)
      ? req.body.actions.map((v: unknown) => String(v).trim()).filter(Boolean)
      : [];
    if (!storeId || !weekId) {
      res.status(400).json({ success: false, message: "storeId 与 weekId 必填" });
      return;
    }
    const all = readActionPlans().filter((it) => !(it.store_id === storeId && it.week_id === weekId));
    const stamp = nowIso();
    const next = actions.map((detail, idx) => ({
      id: `${storeId}-${weekId}-${idx + 1}-${Date.now()}`,
      store_id: storeId,
      week_id: weekId,
      title: `行动${idx + 1}`,
      detail,
      status: "待办",
      created_at: stamp,
      updated_at: stamp,
    }));
    saveActionPlans([...all, ...next]);
    res.json({ success: true, message: "saved" });
  };

  app.post("/api/action-plans", saveHandler);
  app.post("/api/save-actions", saveHandler);

  if (!fs.existsSync(UI_PAYLOAD_PATH)) {
    refreshUiPayloadFromExcel();
  }

  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(ROOT, "dist");
    app.use(express.static(distPath));
    app.get("*", (_req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
