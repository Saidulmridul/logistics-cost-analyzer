"""
formatting.py
--------------
Pure formatting helpers used across pages (renamed from the Streamlit
version's utils.py; the CSS/markup helpers now live in templates instead).
"""


def fmt_currency(x):
    try:
        return f"${x:,.2f}"
    except (TypeError, ValueError):
        return "-"


def fmt_number(x):
    try:
        return f"{x:,.0f}"
    except (TypeError, ValueError):
        return "-"


def fmt_pct(x):
    try:
        return f"{x:.1f}%"
    except (TypeError, ValueError):
        return "-"


APP_TITLE = "Logistics Cost Analyzer"
