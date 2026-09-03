"""
chart_engine.py
-----------------
Shared plotting theme (Executive Dark Slate & Sapphire palette) and helpers so
every page produces visually stunning, modern dashboard charts.
"""

import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Executive Dark Palette & Color Tokens
# ---------------------------------------------------------------------------
PRIMARY = "#F8FAFC"        # Crisp bright white heading
INK = "#E2E8F0"            # Body text
ACCENT = "#3B82F6"         # Sapphire Electric Blue
ACCENT_LIGHT = "#60A5FA"   # Light Blue Accent
CARD_BG = "#1E293B"        # Slate Card Background
APP_BG = "#0F172A"         # Obsidian Dark Background
MUTED = "#94A3B8"          # Muted slate text
GRID_COLOR = "#334155"     # Gridline border color

STATUS_COLORS = {
    "On Time": "#10B981",    # Emerald Green
    "Delayed": "#EF4444",    # Crimson Red
    "Early": "#3B82F6",      # Sapphire Blue
    "Cancelled": "#6B7280",  # Muted Gray
}

# Vibrant modern chart color sequence
COLOR_SEQ = [
    "#3B82F6",  # Electric Sapphire Blue
    "#10B981",  # Emerald Green
    "#8B5CF6",  # Deep Violet
    "#F59E0B",  # Vibrant Amber
    "#EC4899",  # Vivid Pink
    "#06B6D4",  # Cyan Blue
    "#F97316",  # Bright Orange
    "#6366F1",  # Indigo Accent
]

CONTINUOUS_SCALE = "Tealgrn"
CONTINUOUS_SCALE_DIVERGING = "Viridis"

PLOTLY_TEMPLATE = "plotly_dark"


def style_fig(fig, height: int = 400):
    """Apply the executive dark slate theme to any Plotly figure and return it."""
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        height=height,
        paper_bgcolor=CARD_BG,
        plot_bgcolor=CARD_BG,
        font=dict(color=INK, family="Inter, 'Segoe UI', sans-serif", size=12),
        title_font=dict(color=PRIMARY, size=15, family="Inter, sans-serif"),
        legend=dict(
            font=dict(color=INK, size=11),
            bgcolor="rgba(15, 23, 42, 0.5)",
            bordercolor=GRID_COLOR,
            borderwidth=1,
        ),
        margin=dict(t=55, l=15, r=15, b=15),
        hoverlabel=dict(
            bgcolor="#0F172A",
            font_size=12,
            font_family="Inter, sans-serif",
            bordercolor=ACCENT,
        ),
    )
    fig.update_xaxes(
        gridcolor=GRID_COLOR,
        zerolinecolor=GRID_COLOR,
        color=MUTED,
        title_font=dict(color=INK, size=12),
    )
    fig.update_yaxes(
        gridcolor=GRID_COLOR,
        zerolinecolor=GRID_COLOR,
        color=MUTED,
        title_font=dict(color=INK, size=12),
    )
    
    # Enable rounded bar corners if bar charts are present
    fig.update_traces(
        selector=dict(type='bar'),
        marker=dict(cornerradius=5)
    )
    
    return fig


def empty_fig(message: str):
    """A minimal placeholder figure for when required data isn't available."""
    fig = go.Figure()
    fig.add_annotation(
        text=message, showarrow=False, font=dict(size=13, color=MUTED),
        xref="paper", yref="paper", x=0.5, y=0.5,
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style_fig(fig, height=220)
