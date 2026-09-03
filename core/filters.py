"""
filters.py
-----------
Builds filter definitions dynamically -- only for standard fields that
actually exist (and have data) in the current working DataFrame -- and
applies them based on URL query parameters. This replaces the Streamlit
sidebar-widget version: filters are now plain GET query params, so every
filtered view is bookmarkable/shareable, and "reset" is just the bare URL.
"""

import pandas as pd

from .schema import DIMENSION_KEYS_FOR_FILTERS, FIELD_MAP

FILTER_LABELS = {
    "origin": "Origin", "destination": "Destination", "route": "Route",
    "vehicle": "Vehicle", "transport_mode": "Transport Mode", "warehouse": "Warehouse",
    "customer": "Customer", "supplier": "Supplier / Carrier", "driver": "Driver",
    "product_category": "Product Category", "delivery_status": "Delivery Status",
}


def build_filter_config(df: pd.DataFrame) -> dict:
    """Describe which filter widgets should be shown for this dataset,
    and their available options -- always computed off the FULL (unfiltered)
    dataframe, matching the original app's behavior."""
    config = {"has_date": False, "min_date": None, "max_date": None, "dimensions": []}

    if df is None or df.empty:
        return config

    if "date" in df.columns and df["date"].notna().any():
        config["has_date"] = True
        config["min_date"] = df["date"].min().date().isoformat()
        config["max_date"] = df["date"].max().date().isoformat()

    for key in DIMENSION_KEYS_FOR_FILTERS:
        if key == "date" or key not in df.columns:
            continue
        if df[key].dropna().empty:
            continue
        options = sorted(df[key].dropna().unique().tolist())
        if len(options) < 2:
            continue
        label = FILTER_LABELS.get(key, FIELD_MAP[key].label if key in FIELD_MAP else key)
        config["dimensions"].append({"key": key, "label": label, "options": options})

    return config


def apply_filters(df: pd.DataFrame, args) -> pd.DataFrame:
    """Apply filters described by `args` (a Flask request.args-like MultiDict)
    to df. Mirrors the original apply_sidebar_filters filtering logic."""
    if df is None or df.empty:
        return df

    filtered = df.copy()

    if "date" in df.columns and df["date"].notna().any():
        start_date = args.get("date_start")
        end_date = args.get("date_end")
        min_date = df["date"].min().date()
        max_date = df["date"].max().date()
        try:
            start_date = pd.to_datetime(start_date).date() if start_date else min_date
        except (ValueError, TypeError):
            start_date = min_date
        try:
            end_date = pd.to_datetime(end_date).date() if end_date else max_date
        except (ValueError, TypeError):
            end_date = max_date
        filtered = filtered[
            (filtered["date"].dt.date >= start_date) & (filtered["date"].dt.date <= end_date)
        ]

    for key in DIMENSION_KEYS_FOR_FILTERS:
        if key == "date" or key not in df.columns:
            continue
        if df[key].dropna().empty:
            continue
        selected = args.getlist(key) if hasattr(args, "getlist") else args.get(key, [])
        if selected:
            filtered = filtered[filtered[key].isin(selected)]

    return filtered
