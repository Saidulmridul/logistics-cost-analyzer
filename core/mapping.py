"""
mapping.py
-----------
Applies a user-confirmed column mapping to a raw uploaded DataFrame,
producing a DataFrame that uses the app's standard internal field names,
plus derives fields (route, total_cost, profit, month, etc.) whenever the
raw data doesn't already provide them.
"""

import numpy as np
import pandas as pd

from .schema import FIELD_MAP, COST_FIELD_KEYS


def apply_mapping(raw_df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Rename mapped columns onto standard keys; unmapped standard fields are skipped."""
    rename = {col: key for key, col in mapping.items() if col}
    df = raw_df.rename(columns=rename).copy()

    # Keep only standardized + any leftover original columns (leftover kept for Data Explorer)
    return df


def available_fields(df: pd.DataFrame) -> dict:
    """Return {field_key: bool} for every standard field, after mapping + derivation."""
    return {key: (key in df.columns and df[key].notna().any()) for key in FIELD_MAP}


def derive_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Compute fields that can be inferred from other columns when missing."""
    df = df.copy()

    # Route from origin/destination
    if "route" not in df.columns or df["route"].isna().all():
        if "origin" in df.columns and "destination" in df.columns:
            df["route"] = df["origin"].astype(str) + " → " + df["destination"].astype(str)
        elif "warehouse" in df.columns and "destination" in df.columns:
            df["route"] = df["warehouse"].astype(str) + " → " + df["destination"].astype(str)

    # Total cost from components
    present_cost_cols = [c for c in COST_FIELD_KEYS if c in df.columns]
    if ("total_cost" not in df.columns or df["total_cost"].isna().all()) and present_cost_cols:
        df["total_cost"] = df[present_cost_cols].sum(axis=1, skipna=True)

    # Profit from revenue - total_cost
    if ("profit" not in df.columns or df["profit"].isna().all()):
        if "revenue" in df.columns and "total_cost" in df.columns:
            df["profit"] = df["revenue"] - df["total_cost"]

    # Profit margin %
    if "revenue" in df.columns and "profit" in df.columns:
        df["profit_margin_pct"] = np.where(
            df["revenue"] > 0, (df["profit"] / df["revenue"]) * 100, 0.0
        )

    # Cost per km
    if "total_cost" in df.columns and "distance_km" in df.columns:
        df["cost_per_km"] = np.where(
            df["distance_km"] > 0, df["total_cost"] / df["distance_km"], np.nan
        )

    # Month bucket for trend charts
    if "date" in df.columns:
        df["month"] = df["date"].dt.to_period("M").astype(str)

    # Delay flag: prefer explicit status, else compare planned vs actual delivery time
    if "delivery_status" not in df.columns or df["delivery_status"].isna().all():
        if "delivery_time_hours" in df.columns and "planned_delivery_time_hours" in df.columns:
            df["delivery_status"] = np.where(
                df["delivery_time_hours"] > df["planned_delivery_time_hours"],
                "Delayed", "On Time",
            )

    if "delivery_status" in df.columns:
        df["is_delayed"] = df["delivery_status"].astype(str).str.strip().str.lower().eq("delayed")

    return df
