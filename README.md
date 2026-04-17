# Restaurant Weekly Data Analysis Dashboard - Implementation Guide

This repository contains a complete design and logic specification for a restaurant analytics dashboard. It is designed to be handed over to **Cursor** for final implementation and data integration.

## 1. File Structure
- `PROJECT_SPEC.md`: The "Source of Truth" document. Give this to Cursor first to set the context.
- `data_processor.py`: The **Backend Engine**. This is where all the math happens.
- `app.py`: The **Frontend UI**. This uses Streamlit and custom CSS to create a professional dashboard.

## 2. How to use with Cursor
1.  **Context Loading**: Open Cursor and add `PROJECT_SPEC.md` to the chat context (use `@PROJECT_SPEC.md`).
2.  **Implementation**: Ask Cursor: 
    > "Based on the `@PROJECT_SPEC.md`, implement the `data_processor.py` and `app.py`. Ensure the backend handles all calculations and the frontend follows the 'Technical Dashboard' aesthetic."
3.  **Data Integration**: If you have your own CSV data, provide the file to Cursor and ask:
    > "Modify the `_load_data` method in `data_processor.py` to read from my attached CSV file instead of using mock data. Ensure the column mapping matches the schema in the spec."

## 3. Key Design Features
- **Monospace Data**: All numeric values use `JetBrains Mono` for a precise, technical feel.
- **Serif Accents**: Headers use `Playfair Display` to add a sophisticated, human touch to the business data.
- **KPI Cards**: Custom-styled cards with visible borders and WoW (Week-over-Week) indicators.
- **Strict Separation**: No business logic is allowed in `app.py`. If you need a new metric, add it to `data_processor.py` first.

## 4. Running the App (Locally)
If you have Python installed locally, you can run the dashboard with:
```bash
pip install streamlit pandas numpy plotly
streamlit run app.py
```

## 5. 当前仓库的真实数据版（中文简要）

- 将每家门店导出的 Excel 放到 `data/<门店文件夹>/`（例如 `data/紫竹`、`data/夕佳悦`）。
- 周度汇总会合并写入 `data/warehouse/weekly_metrics.json`：同一门店同一自然周（周一为周标识）重复导入会覆盖更新，旧周会保留。
- 行动计划保存在 `data/warehouse/action_plans.json`。
- Streamlit Cloud：建议把 `data/warehouse/*.json` 纳入 Git；如需云端自动回写 GitHub，请在 Streamlit Secrets 配置 `GITHUB_TOKEN`、`GITHUB_REPO_OWNER`、`GITHUB_REPO_NAME`、`GITHUB_BRANCH`（可选 `GITHUB_BRANCH`，默认 `main`）。
