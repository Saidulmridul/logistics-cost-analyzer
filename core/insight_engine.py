"""
insight_engine.py
-------------------
Rule-based (no AI) business insights generated purely from pandas
aggregations of whatever standard fields the current dataset provides.
"""

import pandas as pd
from .kpi_engine import has


def generate_insights(df: pd.DataFrame) -> list:
    insights = []
    if df is None or df.empty:
        return [{"icon": "⚠️", "title": "No data available", "detail": "Adjust your filters or upload a dataset."}]

    active = df
    if "delivery_status" in df.columns:
        active = df[df["delivery_status"].astype(str).str.lower() != "cancelled"]
        if active.empty:
            active = df

    # Highest / lowest cost driver among cost components present
    cost_component_labels = {
        "transportation_cost": "Transportation Cost", "fuel_cost": "Fuel Cost",
        "warehouse_cost": "Warehouse Cost", "labor_cost": "Labor Cost",
        "customs_cost": "Customs Cost", "insurance_cost": "Insurance Cost",
        "maintenance_cost": "Maintenance Cost", "toll_cost": "Toll Cost",
        "other_cost": "Other Charges",
    }
    present_components = {k: v for k, v in cost_component_labels.items() if k in active.columns}
    if present_components:
        totals = {label: active[key].sum() for key, label in present_components.items()}
        total_all = sum(totals.values())
        if total_all > 0:
            top_label, top_val = max(totals.items(), key=lambda x: x[1])
            low_label, low_val = min(totals.items(), key=lambda x: x[1])
            insights.append({
                "icon": "💰", "title": f"Highest Cost Driver: {top_label}",
                "detail": f"{top_label} contributes {top_val / total_all * 100:.1f}% of total logistics expenses.",
            })
            if low_label != top_label:
                insights.append({
                    "icon": "🟢", "title": f"Lowest Cost Driver: {low_label}",
                    "detail": f"{low_label} contributes only {low_val / total_all * 100:.1f}% of total logistics expenses.",
                })

    # Most expensive / most profitable route
    if has(active, "route", "total_cost"):
        route_cost = active.groupby("route")["total_cost"].sum().sort_values(ascending=False)
        if not route_cost.empty:
            insights.append({
                "icon": "🛣️", "title": f"Most Expensive Route: {route_cost.index[0]}",
                "detail": f"Total cost of ${route_cost.iloc[0]:,.2f} across all shipments on this route.",
            })
    if has(active, "route", "profit"):
        route_profit = active.groupby("route")["profit"].sum().sort_values(ascending=False)
        if not route_profit.empty:
            insights.append({
                "icon": "🏆", "title": f"Most Profitable Route: {route_profit.index[0]}",
                "detail": f"Generated ${route_profit.iloc[0]:,.2f} in total profit.",
            })

    # Lowest-cost transport mode
    if has(active, "transport_mode", "total_cost"):
        mode_cost = active.groupby("transport_mode")["total_cost"].mean().sort_values()
        if not mode_cost.empty:
            insights.append({
                "icon": "🚛", "title": f"Lowest-Cost Transport Mode: {mode_cost.index[0]}",
                "detail": f"Averages ${mode_cost.iloc[0]:,.2f} per shipment — the most economical mode in this dataset.",
            })

    # Fastest delivery route
    if has(active, "route", "delivery_time_hours"):
        route_time = active.groupby("route")["delivery_time_hours"].mean().sort_values()
        if not route_time.empty:
            insights.append({
                "icon": "⚡", "title": f"Fastest Delivery Route: {route_time.index[0]}",
                "detail": f"Averages {route_time.iloc[0]:.1f} hours per delivery — the quickest route on record.",
            })

    # Highest delay route
    if has(df, "route", "is_delayed"):
        route_delay = df.groupby("route")["is_delayed"].mean().sort_values(ascending=False)
        if not route_delay.empty and route_delay.iloc[0] > 0:
            insights.append({
                "icon": "⏱️", "title": f"Highest Delay Route: {route_delay.index[0]}",
                "detail": f"{route_delay.iloc[0] * 100:.1f}% of shipments on this route were delayed.",
            })

    # Best performing vehicle (lowest operating cost)
    if has(active, "vehicle", "total_cost"):
        veh_cost = active.groupby("vehicle")["total_cost"].mean().sort_values()
        if not veh_cost.empty:
            insights.append({
                "icon": "🔧", "title": f"Lowest Operating Cost Vehicle: {veh_cost.index[0]}",
                "detail": f"Averages ${veh_cost.iloc[0]:,.2f} in total cost per shipment.",
            })

    # Revenue / profit trend direction
    if has(df, "month", "revenue"):
        monthly_rev = df.groupby("month")["revenue"].sum().sort_index()
        if len(monthly_rev) >= 2:
            direction = "up" if monthly_rev.iloc[-1] >= monthly_rev.iloc[0] else "down"
            insights.append({
                "icon": "📈" if direction == "up" else "📉",
                "title": f"Revenue Trend is Trending {direction.title()}",
                "detail": f"Revenue moved from ${monthly_rev.iloc[0]:,.2f} to ${monthly_rev.iloc[-1]:,.2f} "
                          f"over the period shown.",
            })
    if has(df, "month", "profit"):
        monthly_profit = df.groupby("month")["profit"].sum().sort_index()
        if len(monthly_profit) >= 2:
            direction = "up" if monthly_profit.iloc[-1] >= monthly_profit.iloc[0] else "down"
            insights.append({
                "icon": "📈" if direction == "up" else "📉",
                "title": f"Profit Trend is Trending {direction.title()}",
                "detail": f"Profit moved from ${monthly_profit.iloc[0]:,.2f} to ${monthly_profit.iloc[-1]:,.2f} "
                          f"over the period shown.",
            })

    # Overall delay rate
    if "is_delayed" in df.columns:
        delay_rate = df["is_delayed"].mean() * 100
        insights.append({
            "icon": "🚦", "title": f"Overall Delay Rate: {delay_rate:.1f}%",
            "detail": "Consider reviewing routing and scheduling if this exceeds 15-20%."
                      if delay_rate > 15 else "Delivery performance is within a healthy range.",
        })

    if not insights:
        insights.append({
            "icon": "ℹ️", "title": "Not enough mapped fields for detailed insights",
            "detail": "Map more columns (cost, route, revenue, delivery time) in the upload step to unlock richer insights.",
        })

    return insights
