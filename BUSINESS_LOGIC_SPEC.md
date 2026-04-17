# Business Logic & Calculation Specification: Restaurant Dashboard

This document defines the exact calculation rules, judgment standards, and logic used in the Restaurant Weekly Analytics Dashboard. Use this as the primary reference for implementing the `data_processor.py` backend.

## 1. Core Metrics & Status Standards
All metrics are compared Week-over-Week (WoW).

| Metric | Calculation Formula | Status: Red (🔴) | Status: Yellow (🟡) | Status: Green (🟢) |
| :--- | :--- | :--- | :--- | :--- |
| **Total Revenue** | `sum(daily_revenue)` | WoW Drop > 10% for 2 consecutive weeks | WoW Fluctuation ±15% | WoW Growth > 0% or stable |
| **Total Orders** | `count(order_id)` | WoW Drop > 5% | WoW Drop 2% - 5% | WoW Growth > 0% |
| **Avg Order Value (AOV)** | `Revenue / Orders` | - | WoW Fluctuation ±15% | Stable (±5%) |
| **Retention Rate** | `Repeat_Customers / Total_Customers` | - | WoW Drop > 5% | WoW Growth > 0% |

## 2. Time-Based Analysis Logic
### 2.1. Period Definitions
- **Morning (上午)**: 08:00 - 10:30
- **Lunch (午餐)**: 10:30 - 14:00
- **Afternoon Tea (下午茶)**: 14:00 - 17:00
- **Dinner (晚餐)**: 17:00 - 21:00

### 2.2. Table Turnover Rate (翻台率)
- **Formula**: `Orders in Period / Total Tables`
- **Standard**: Assume a fixed `Total Tables` per store (e.g., 50 tables).
- **Judgment**: 
  - Lunch/Dinner > 3.0 is Excellent.
  - Any period < 0.5 is "Underperforming" (except Morning/Tea).

### 2.3. Anomaly Detection (时段异常)
- **High Peak**: If a specific day's period revenue or orders is > 20% higher than the 4-week average for that same period.
- **Low Peak**: If revenue is < 30% of the 4-week average, OR impacted by weather (see Section 4).

## 3. Product & Category Logic
- **Top 5 / Bottom 5**: Ranked by total sales volume (`count`) and total revenue (`sum`).
- **Product Returns**: 
  - **Standard**: If `Returns > 5` per week -> Status: Yellow (🟡).
- **Loss Amount (报损)**:
  - **Standard**: If `WoW Increase > 30%` -> Status: Red (🔴).
- **Category Trend**: `(This_Week_Sales - Last_Week_Sales) / Last_Week_Sales`.

## 4. External Environment & Weather Impact
### 4.1. Special Date Grouping
- **Weekdays (周平日)**: Mon - Fri.
- **Weekends (周末)**: Sat - Sun.
- **Holidays**: Defined by a static calendar.
- **Calculation**: Compare `Avg Daily Revenue` of the special period vs. `Avg Daily Revenue` of normal weekdays in the same month.

### 4.2. Weather Impact Analysis
- **Normal Avg Revenue**: Average revenue of "Sunny" or "Cloudy" days in the current week.
- **Abnormal Avg Revenue**: Average revenue of "Rainy", "Snowy", or "Extreme Heat" days.
- **Impact Judgment**: If `(Normal_Avg - Abnormal_Avg) / Normal_Avg > 30%`, then `isImpacted = "Yes"`.

## 5. Keyword Extraction & AI Summary Logic
### 5.1. Keyword Extraction (NLP/Frequency)
- **Good Keywords**: Top 3 most frequent nouns/adjectives in reviews with Rating >= 4.
- **Bad Keywords**: Top 3 most frequent nouns/adjectives in reviews with Rating <= 2.
- **Specific Triggers**: If "Wait time" or "Slow" appears in > 10% of reviews, "上菜慢" (Slow Service) becomes a mandatory Bad Keyword.

### 5.2. Highlights & Problems (Output Logic)
- **Highlight Generation**:
  - Trigger 1: If Weekend Revenue Growth > 10% -> Mention "Weekend Peak".
  - Trigger 2: If a specific category grew > 15% -> Mention "Category Success".
  - Trigger 3: If Good Keywords are consistent -> Mention "Customer Recognition".
- **Problem Generation**:
  - Trigger 1: If Weather Impact is "Yes" -> Mention "Weather Vulnerability".
  - Trigger 2: If Rating dropped > 0.2 points -> Mention "Service Quality Decline".
  - Trigger 3: If Returns/Loss triggered Red status -> Mention "Operational Waste".

## 6. Action Plan (Manual Input)
- **Constraint**: Maximum 3 items.
- **Storage**: Must be persisted in SQLite, keyed by `(store_id, week_id)`.
- **Default**: If no manual input exists, provide 3 generic suggestions based on the "Problems" identified in Section 5.2.
