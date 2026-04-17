# Project Specification: Restaurant Weekly Data Analysis Dashboard

## 1. Overview
A professional, high-performance business analytics dashboard built with **Python** and **Streamlit**. The application follows a strict **Server-Side Computation** architecture: the backend handles all data processing, metrics calculation, and business logic, while the frontend (Streamlit UI) is responsible only for rendering the pre-calculated results.

## 2. Tech Stack
- **Language**: Python 3.10+
- **Framework**: Streamlit (Frontend & App Server)
- **Data Processing**: Pandas, NumPy
- **Visualization**: Plotly (for interactive charts)
- **Styling**: Custom CSS (Technical Dashboard / Data Grid aesthetic)

## 3. Data Architecture
### 3.1. Data Source
- **Format**: CSV or SQLite (Historical weekly data).
- **Schema**:
  - `week_id`: String (e.g., "2024-W12")
  - `revenue`: Float
  - `orders`: Integer
  - `table_turnover_rate`: Float (0.0 - 5.0+)
  - `avg_order_value`: Float
  - `labor_cost`: Float
  - `food_cost`: Float

### 3.2. Backend Logic (`data_processor.py`)
The backend must provide a `MetricsEngine` class with the following methods:
- `get_weekly_summary(week_id)`: Returns a dictionary of core metrics for the specified week.
- `calculate_wow_change(current_week_id)`: Calculates Week-over-Week percentage changes for all core metrics.
- `get_trend_data(metric_name, weeks_count=8)`: Returns time-series data for charting.
- **Strict Rule**: No raw data filtering or `sum()` operations should happen in the `app.py` UI layer.

## 4. Frontend Design Specification
### 4.1. Aesthetic: Technical Dashboard (Recipe 1)
- **Mood**: Professional, precise, information-dense.
- **Color Palette**:
  - Background: `#F8F9FA` (Light Gray)
  - Text: `#1A1A1A` (Deep Ink)
  - Accents: `#0066FF` (Action Blue), `#28A745` (Success Green), `#DC3545` (Danger Red)
- **Typography**:
  - Headers: Serif (Georgia/Playfair Display) for a human touch.
  - Data Values: Monospace (JetBrains Mono/Courier) for precision.

### 4.2. Layout Structure
1.  **Sidebar**: Week selector, Store selector, Export buttons.
2.  **Top Row (KPI Cards)**: 4-5 cards showing Revenue, Orders, Turnover, and WoW changes.
3.  **Middle Row (Main Charts)**: 
    - Left: Revenue & Order Trend (Dual-axis line chart).
    - Right: Cost Breakdown (Donut chart).
4.  **Bottom Row (Detailed Data Grid)**: A scannable table of daily breakdowns for the selected week.

## 5. Implementation Instructions for Cursor
1.  **Backend First**: Implement `data_processor.py` to handle all CSV loading and math. Ensure it returns clean dictionaries/DataFrames.
2.  **UI Scaffolding**: Use `st.set_page_config` for a wide layout. Use `st.columns` for the KPI cards.
3.  **Custom CSS**: Inject CSS to style the KPI cards with visible borders and monospace values.
4.  **Charts**: Use `plotly.graph_objects` for fine-grained control over colors and axes.
