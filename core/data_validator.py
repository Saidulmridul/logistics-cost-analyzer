"""
data_validator.py
-------------------
Validates a raw uploaded DataFrame (and its proposed column mapping) and
returns friendly warnings/errors instead of letting the app crash.
"""

import pandas as pd
from .schema import FIELD_MAP


def validate_dataset(df: pd.DataFrame, mapping: dict) -> dict:
    """
    Returns {"errors": [...], "warnings": [...]}.
    Errors block moving forward (e.g. empty dataset).
    Warnings are informational and the app continues gracefully.
    """
    errors, warnings = [], []

    if df is None or df.empty:
        errors.append("The uploaded file contains no rows. Please upload a non-empty dataset.")
        return {"errors": errors, "warnings": warnings}

    if df.shape[1] == 0:
        errors.append("The uploaded file has no columns.")
        return {"errors": errors, "warnings": warnings}

    # Required fields
    for key, fdef in FIELD_MAP.items():
        if fdef.required and not mapping.get(key):
            warnings.append(
                f"'{fdef.label}' is not mapped to any column. Date-based trends will be hidden."
            )

    # Do we have any cost signal at all?
    cost_keys = [k for k, f in FIELD_MAP.items() if f.group == "cost"]
    has_any_cost = any(mapping.get(k) for k in cost_keys) or mapping.get("total_cost")
    if not has_any_cost:
        warnings.append(
            "No cost columns were mapped (transportation, fuel, warehouse, labor, "
            "customs, insurance, or a total cost column). Cost KPIs and charts will be hidden."
        )

    if not mapping.get("revenue"):
        warnings.append("No revenue column mapped — profit and margin metrics will be hidden.")

    # Duplicate rows
    dup_count = int(df.duplicated().sum())
    if dup_count > 0:
        warnings.append(f"{dup_count:,} duplicate row(s) detected — these will be removed automatically.")

    # Missing values
    total_missing = int(df.isna().sum().sum())
    if total_missing > 0:
        warnings.append(f"{total_missing:,} missing value(s) found — these will be handled automatically.")

    # Validate numeric columns mapped for numeric fields
    for key, col in mapping.items():
        if not col or col not in df.columns:
            continue
        fdef = FIELD_MAP.get(key)
        if fdef is None:
            continue
        if fdef.dtype == "numeric":
            coerced = pd.to_numeric(df[col], errors="coerce")
            bad = int(coerced.isna().sum() - df[col].isna().sum())
            if bad > 0:
                warnings.append(
                    f"Column '{col}' mapped to '{fdef.label}' has {bad:,} non-numeric value(s); "
                    "they will be treated as missing."
                )
        elif fdef.dtype == "date":
            coerced = pd.to_datetime(df[col], errors="coerce")
            bad = int(coerced.isna().sum() - df[col].isna().sum())
            if bad > 0:
                warnings.append(
                    f"Column '{col}' mapped to '{fdef.label}' has {bad:,} invalid date value(s); "
                    "they will be treated as missing."
                )

    return {"errors": errors, "warnings": warnings}
