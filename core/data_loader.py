"""
data_loader.py
---------------
Reads an uploaded CSV/Excel file (a Flask/werkzeug FileStorage object) into
a DataFrame and produces a metadata summary (row/column counts, file size,
missing values) without mutating the original uploaded bytes.
"""

import io
import pandas as pd


def load_uploaded_file(file_storage) -> pd.DataFrame:
    """Read a werkzeug FileStorage (CSV or Excel) into a raw DataFrame."""
    name = (file_storage.filename or "").lower()
    raw_bytes = file_storage.read()
    file_storage.seek(0)

    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(raw_bytes))
    elif name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(raw_bytes))
    else:
        raise ValueError("Unsupported file type. Please upload a .csv or .xlsx file.")

    return df


def file_metadata(filename: str, raw_bytes: bytes, df: pd.DataFrame) -> dict:
    """Build the summary block shown right after upload."""
    size_bytes = len(raw_bytes)
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / 1024 ** 2:.2f} MB"

    missing = df.isna().sum()
    missing = missing[missing > 0].sort_values(ascending=False)
    missing_summary = {col: int(cnt) for col, cnt in missing.items()}

    return {
        "file_name": filename,
        "file_size": size_str,
        "n_rows": int(df.shape[0]),
        "n_cols": int(df.shape[1]),
        "missing_summary": missing_summary,
        "total_missing_cells": int(df.isna().sum().sum()),
    }
