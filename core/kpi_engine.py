"""
kpi_engine.py
--------------
Computes headline KPIs dynamically, only using whatever standard fields
are actually present in the working DataFrame. Replaces the old fixed-schema
utils.compute_kpis.
"""

import pandas as pd


def compute_kpis(df: pd.DataFrame) -> dict:
    """Compute every KPI that current data supports; missing inputs -> None (hidden by caller)."""
    k = {}
    if df is None or df.empty:
        return k

    k["Total Shipments"] = len(df)

    if "total_cost" in df.columns:
        k["Total Logistics Cost"] = round(float(df["total_cost"].sum()), 2)
        k["Avg Cost per Shipment"] = round(float(df["total_cost"].mean()), 2)

    if "revenue" in df.columns:
        k["Total Revenue"] = round(float(df["revenue"].sum()), 2)

    if "profit" in df.columns:
        k["Total Profit"] = round(float(df["profit"].sum()), 2)
        if "revenue" in df.columns and df["revenue"].sum():
            k["Profit Margin (%)"] = round(float(df["profit"].sum() / df["revenue"].sum() * 100), 2)

    if "distance_km" in df.columns:
        k["Total Distance (km)"] = round(float(df["distance_km"].sum()), 1)
        if "total_cost" in df.columns and df["distance_km"].sum():
            k["Avg Cost per Km"] = round(float(df["total_cost"].sum() / df["distance_km"].sum()), 2)

    if "weight" in df.columns:
        k["Total Weight"] = round(float(df["weight"].sum()), 1)

    if "delivery_time_hours" in df.columns:
        k["Avg Delivery Time (hrs)"] = round(float(df["delivery_time_hours"].mean()), 2)

    if "delivery_status" in df.columns:
        delayed = df["delivery_status"].astype(str).str.lower().eq("delayed")
        k["Delay Rate (%)"] = round(float(delayed.mean() * 100), 2)
        k["On-Time Rate (%)"] = round(float(df["delivery_status"].astype(str).str.lower().eq("on time").mean() * 100), 2)

    return k


def has(df: pd.DataFrame, *cols) -> bool:
    """True if every given standard column exists and has at least one non-null value."""
    return all(c in df.columns and df[c].notna().any() for c in cols)
