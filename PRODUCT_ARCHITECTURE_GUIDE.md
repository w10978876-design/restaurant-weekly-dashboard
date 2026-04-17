# 餐厅周度经营看板：产品架构与计算说明

本文档用于快速掌握当前版本的页面结构、数据链路与核心计算逻辑，作为产品与研发协作的统一参考。

---

## 1. 产品目标与边界

- **目标**：将多门店 Excel 经营数据自动汇总为按周可读的经营看板，输出核心指标、时段异常、品类/菜品表现、服务反馈与综合结论。
- **边界**：
  - 本系统以“自然周（周一~周日）”为统计粒度。
  - 计算在后端完成，前端仅展示 `ui_payload.json`。
  - 行动计划支持人工编辑与持久化（独立存储）。

---

## 2. 当前系统结构

### 2.1 数据输入层

- 数据目录：`data/<门店>/`
- 主要来源文件（每门店）：
  - 店内订单明细
  - 支付明细
  - 菜品销售明细
  - 菜品报损统计
  - 店内评价管理
  - 团购核销明细
  - 菜品库 / 品类映射

读取与标准化由 `ingestion/` 完成，聚合为 `StoreBundle`。

### 2.2 计算层

- 主构建入口：`core/dashboard_builder.py`
  - 函数：`build_ui_payload()`、`write_ui_payload()`
- 指标引擎：`core/metrics_engine.py`
- 关键词提炼：`core/review_nlp.py`
- 综合结论生成：`data_processor.py::generate_summary()`

### 2.3 输出层

- 前端主数据：`data/warehouse/ui_payload.json`
- 周度指标持久化：`data/warehouse/weekly_metrics.json`
- 行动计划：`data/warehouse/action_plans.json`
- 质检报表（辅助）：`data/warehouse/keyword_quality_report.md`

---

## 3. 页面结构（对应 payload）

单门店单周（`stores.<store_id>.weeks.<week_id>`）包含：

- `coreMetrics`：核心 KPI 卡片（营收、订单、客单价、复购率）
- `categoryAnalysis`：类目销售与趋势
- `productDetails`：
  - `topSales` / `topRevenue` / `bottomSales`
  - `returns`（退换菜）
  - `lossAmount`（报损）
- `timeAnalysis`：
  - 时段表（上午/午餐/下午茶/晚餐）
  - 异常时段摘要
  - 低订单日
- `marketing`：团购与自然进店占比
- `service`：
  - 差评数与评分状态
  - 好评/差评关键词
  - 关键词证据句与候选池（用于可解释性）
- `externalAndWeather`：天气与特殊日期
- `summary`：综合结论（亮点/问题/行动）
- `trendData`：时间序列趋势
- `weeklyTable`：周级明细快照

---

## 4. 核心计算逻辑（当前实现）

### 4.1 周口径与环比

- 周标识：`week_id`（周一日期）
- 环比公式：`(本周-上周)/上周`
- 状态判定由 `core/status_rules.py` 提供（营收、订单、客单价、复购）

### 4.2 时段切分与异常

- 时段：
  - 上午：08:00-10:30
  - 午餐：10:30-14:00
  - 下午茶：14:00-17:00
  - 晚餐：17:00-21:00
- 翻台率：`时段订单数 / TOTAL_TABLES`（当前 `TOTAL_TABLES=50`）
- 异常检测：
  - 与历史窗口同组样本（平日/周末 + 同时段）比较
  - 高峰/低谷按收入与订单偏离阈值识别

### 4.3 菜品与品类

- 品类以销售明细主键与映射表关联，未命中归“未映射类目”
- 菜品榜单按销量与收入生成 Top/Bottom
- 退菜与报损采用周累计 + 环比阈值判定

### 4.4 天气影响

- 逐日天气映射后计算异常天气与正常天气的日均营收
- 若异常天气影响超过阈值，写入天气影响结论

---

## 5. 关键词提炼逻辑（服务模块）

### 5.1 入池规则（当前已稳定）

- 好评池：`score >= 4`
- 差评池：`score <= 3`

### 5.2 提炼策略

- 主提炼：从原文抽取“对象 + 评价”短语（名词/状态词 + 评价补足）
- 质量增强：
  - 优先具体对象，弱化泛词（如仅“味道不错”）
  - 差评优先“原因 -> 结果”短语（如“密度过高导致用餐体验很差”）
  - 过滤低质量/病句短语（分词误切、语义残片）
- 兜底策略：
  - 当池子非空但主提炼为空时，启用句子级语义兜底，确保不为空
  - 兜底按“对象+问题动作/状态”动态生成，不使用单一固定模板
  - 支持跨句主题承接（例如前句“预制菜”，后句“包装上餐问题”）

### 5.3 可解释性输出

- `goodKeywordEvidence` / `badKeywordEvidence`：每个关键词绑定 1-2 条证据句
- `goodKeywordCandidates` / `badKeywordCandidates`：候选池 + 分数 + 排名

---

## 6. 综合结论逻辑（summary）

`summary` 现在由 `data_processor.generate_summary()` 统一生成，并在 `core/dashboard_builder.py` 接入。

输入信号包括：

- KPI 环比（营收、订单）
- 时段异常摘要（high/low）
- 好评/差评关键词
- 天气影响摘要
- 评分变化
- 退菜与报损预警

输出：

- `highlights`（亮点列表）
- `problems`（问题列表）

前端展示为：

- `summary.highlight`（分号拼接）
- `summary.problem`（分号拼接）
- `summary.actions`（人工行动项）

说明：当前已做文本清洗，避免重复句号与分号叠加，并将关键词从“复读”改为“主题归纳+示例”表达。

---

## 7. 端到端更新流程

1. 更新/替换 `data/<门店>/` 原始 Excel
2. 执行正式周更脚本（推荐）：
   - `PYTHONPATH=. python3 scripts/weekly_update.py`
   - 功能：自动备份 `weekly_metrics.json` 与 `action_plans.json`，再重建 `ui_payload.json`，并输出“历史周是否保留/计划是否保留”的校验结果
3. 如需仅重建前端 payload（不走备份）：
   - `PYTHONPATH=. python3 -m core.dashboard_builder`
3. 产物更新：
   - `data/warehouse/ui_payload.json`
4. 前端刷新读取新 payload

建议同时生成质检报表用于人工核验：

- `data/warehouse/keyword_quality_report.md`

---

## 8. 已知约束与后续优化建议

- 评价文本口语化强、分词误差不可完全避免；当前通过规则与证据输出缓解。
- `summary` 仍偏规则驱动，后续可增加门店个性化模板与行业对标维度。
- 推荐新增“版本快照对比”机制，记录每次规则调整对关键词与结论的影响。

---

## 9. 快速定位（代码索引）

- 主构建：`core/dashboard_builder.py`
- 关键词：`core/review_nlp.py`
- 综合结论：`data_processor.py::generate_summary`
- 数据装载：`ingestion/pipeline.py`
- 指标引擎：`core/metrics_engine.py`

