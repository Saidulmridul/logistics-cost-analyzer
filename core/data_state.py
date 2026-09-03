"""
data_state.py
---------------
Single source of truth for "what dataset is the app currently working
with". Replaces Streamlit's st.session_state with a simple server-side,
per-browser-session in-memory store (keyed by a signed session id cookie
that Flask manages for us).

NOTE on scaling: this store lives in the Python process's memory. That's
fine for a single-process deployment (the default here). If you deploy
with multiple worker processes/machines, either run a single worker, turn
on sticky sessions at your load balancer, or swap SESSION_STORE for
something shared (e.g. Redis) -- the get/set/pop calls below are the only
places that would need to change.
"""

import threading

from .data_generator import generate_shipment_data
from .mapping import derive_fields
from .kpi_engine import has  # noqa: F401  (re-exported for convenience)

_lock = threading.Lock()
SESSION_STORE = {}

_sample_df = None
_sample_lock = threading.Lock()


def _build_sample_dataframe():
    df = generate_shipment_data(n=1500, seed=42)
    df = df.rename(columns={
        "vehicle_type": "transport_mode",
        "other_charges": "other_cost",
    })
    df["vehicle"] = df["transport_mode"] + " - " + df["driver"].str.replace(" ", "")
    df = derive_fields(df)
    return df


def get_sample_dataframe():
    """The sample dataset is deterministic (fixed seed) and identical for
    every visitor, so it's generated once per process and shared."""
    global _sample_df
    if _sample_df is None:
        with _sample_lock:
            if _sample_df is None:
                _sample_df = _build_sample_dataframe()
    return _sample_df


def _get_bucket(session_id: str) -> dict:
    with _lock:
        return SESSION_STORE.setdefault(session_id, {})


def get_active_dataframe(session_id: str):
    """Returns (df, source) where source is "uploaded" or "sample"."""
    bucket = _get_bucket(session_id)
    working_df = bucket.get("working_df")
    if working_df is not None and not working_df.empty:
        return working_df, bucket.get("working_df_source", "uploaded")
    return get_sample_dataframe(), "sample"


def has_uploaded_data(session_id: str) -> bool:
    bucket = _get_bucket(session_id)
    df = bucket.get("working_df")
    return df is not None and not df.empty


def set_raw_upload(session_id: str, fingerprint, raw_df, meta, suggested_mapping):
    bucket = _get_bucket(session_id)
    bucket["upload_fingerprint"] = fingerprint
    bucket["raw_upload_df"] = raw_df
    bucket["upload_meta"] = meta
    bucket["suggested_mapping"] = suggested_mapping
    bucket["mapping_confirmed"] = False


def get_raw_upload(session_id: str):
    bucket = _get_bucket(session_id)
    return bucket.get("raw_upload_df"), bucket.get("upload_meta"), bucket.get("suggested_mapping")


def get_upload_fingerprint(session_id: str):
    return _get_bucket(session_id).get("upload_fingerprint")


def set_working_dataframe(session_id: str, df, column_mapping):
    bucket = _get_bucket(session_id)
    bucket["working_df"] = df
    bucket["working_df_source"] = "uploaded"
    bucket["mapping_confirmed"] = True
    bucket["column_mapping"] = column_mapping


def discard_upload(session_id: str):
    bucket = _get_bucket(session_id)
    for k in ["working_df", "working_df_source", "raw_upload_df", "upload_meta",
              "suggested_mapping", "mapping_confirmed", "upload_fingerprint", "column_mapping"]:
        bucket.pop(k, None)
