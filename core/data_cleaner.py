"""
data_cleaner.py
------------------
Cleans a mapped DataFrame: dedupes, parses dates/numerics, strips text,
handles missing values. Never mutates the original uploaded file — always
operates on a copy.
"""

import numpy as np
import pandas as pd

from .schema import FIELD_MAP


def clean_dataset(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Strip whitespace / standardize casing on text-like standard fields
    for key, fdef in FIELD_MAP.items():
        if key not in df.columns:
            continue
        if fdef.dtype == "text":
            df[key] = df[key].astype(str).str.strip()
            df[key] = df[key].replace({"nan": np.nan, "None": np.nan, "": np.nan})
        elif fdef.dtype == "numeric":
            df[key] = pd.to_numeric(df[key], errors="coerce")
        elif fdef.dtype == "date":
            df[key] = pd.to_datetime(df[key], errors="coerce")

    # Strip whitespace on any remaining object columns (leftover / unmapped columns)
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).str.strip().replace({"nan": np.nan})

    # Drop exact duplicate rows
    df = df.drop_duplicates()

    # Fill missing numeric standard fields with 0 (costs/measures) so KPIs never crash
    for key, fdef in FIELD_MAP.items():
        if key in df.columns and fdef.dtype == "numeric":
            df[key] = df[key].fillna(0)

    # Drop rows with an invalid/missing date if a date column exists — trend charts need it
    if "date" in df.columns:
        df = df[df["date"].notna()]

    df = df.reset_index(drop=True)
    return df
