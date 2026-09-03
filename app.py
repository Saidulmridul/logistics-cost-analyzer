"""
app.py
-------
Logistics Cost Analyzer -- Flask entry point.

Server-rendered HTML pages, Plotly.js charts, plain HTTP file upload/download.
Every page, KPI, chart, and chart insight text adapts automatically to whatever
columns are present in the active dataset.
"""

import io
import json
import uuid
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from flask import Flask, render_template, request, redirect, url_for, send_file, session

from core.schema import FIELDS, suggest_mapping
from core.data_loader import load_uploaded_file, file_metadata
from core.data_validator import validate_dataset
from core.data_cleaner import clean_dataset
from core.mapping import apply_mapping, derive_fields
from core.data_state import (
    get_active_dataframe, has_uploaded_data, set_raw_upload, get_raw_upload,
    get_upload_fingerprint, set_working_dataframe, discard_upload,
)
from core.filters import build_filter_config, apply_filters
from core.kpi_engine import compute_kpis, has
from core.chart_engine import style_fig, empty_fig, COLOR_SEQ, CONTINUOUS_SCALE, CONTINUOUS_SCALE_DIVERGING, STATUS_COLORS
from core.formatting import fmt_currency, fmt_number
from core.insight_engine import generate_insights
from core.export_engine import to_csv_bytes, to_excel_bytes, to_pdf_bytes, figs_to_zip_bytes

app = Flask(__name__)
app.secret_key = "change-this-secret-key-in-production"

COST_LABELS = {
    "transportation_cost": "Transportation", "fuel_cost": "Fuel", "warehouse_cost": "Warehouse",
    "labor_cost": "Labor", "customs_cost": "Customs", "insurance_cost": "Insurance",
    "maintenance_cost": "Maintenance", "toll_cost": "Toll", "other_cost": "Other",
}

NAV_ITEMS = [
    ("home", "Home", "🏠"),
    ("cost_analysis", "Cost Analysis", "💰"),
    ("route_analysis", "Route Analysis", "🛣️"),
    ("vehicle_analysis", "Vehicle Analysis", "🚛"),
    ("warehouse_analysis", "Warehouse Analysis", "🏭"),
    ("delay_analysis", "Delay Analysis", "⏱️"),
    ("profitability_analysis", "Profitability Analysis", "📈"),
    ("business_insights", "Business Insights", "💡"),
    ("data_explorer", "Data Explorer", "🔎"),
    ("reports", "Reports", "🧾"),
]


def get_session_id():
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


def chart_payload(charts: dict) -> str:
    """Serialize a dict of {div_id: plotly Figure} to a JSON blob for Plotly.newPlot."""
    payload = {}
    for key, fig in charts.items():
        payload[key] = json.loads(fig.to_json())
    return json.dumps(payload)


def base_context(active_endpoint, full_df, filtered_df):
    filter_config = build_filter_config(full_df)
    return dict(
        nav_items=NAV_ITEMS,
        active_endpoint=active_endpoint,
        filter_config=filter_config,
        request_args=request.args,
        match_count=len(filtered_df) if filtered_df is not None else 0,
        total_count=len(full_df) if full_df is not None else 0,
    )


def load_filtered(session_id):
    full_df, source = get_active_dataframe(session_id)
    filtered_df = apply_filters(full_df, request.args)
    return full_df, source, filtered_df


def table_to_rows(df: pd.DataFrame):
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].round(2)
    return out.values.tolist()


# ---------------------------------------------------------------------------
# Home / upload / mapping
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    sid = get_session_id()
    full_df, source, filtered_df = load_filtered(sid)

    raw_df, meta, suggested = get_raw_upload(sid)
    mapping_groups = None
    if raw_df is not None:
        raw_columns = ["— None —"] + list(raw_df.columns)
        groups = ["dimension", "measure", "cost", "financial", "status"]
        group_labels = {
            "dimension": "Dimensions (route, warehouse, vehicle, etc.)",
            "measure": "Measures (distance, weight, delivery time)",
            "cost": "Cost Components",
            "financial": "Financials (revenue, total cost, profit)",
            "status": "Status",
        }
        mapping_groups = []
        for g in groups:
            fields_in_group = [f for f in FIELDS if f.group == g]
            if not fields_in_group:
                continue
            field_rows = []
            for f in fields_in_group:
                default_col = suggested.get(f.key) if suggested else None
                field_rows.append({
                    "key": f.key, "label": f.label, "required": f.required,
                    "default": default_col if default_col in raw_columns else "— None —",
                })
            mapping_groups.append({"label": group_labels[g], "fields": field_rows})
        preview_rows = raw_df.head(8).to_dict(orient="records")
        preview_cols = list(raw_df.columns)
    else:
        raw_columns = []
        preview_rows, preview_cols = [], []

    if filtered_df.empty:
        kpi_list, chart_data, chart_details = [], "{}", {}
    else:
        kpis = compute_kpis(filtered_df)
        kpi_order = [
            ("Total Shipments", lambda: fmt_number(kpis["Total Shipments"])),
            ("Total Logistics Cost", lambda: fmt_currency(kpis["Total Logistics Cost"])),
            ("Total Revenue", lambda: fmt_currency(kpis["Total Revenue"])),
            ("Total Profit", lambda: fmt_currency(kpis["Total Profit"])),
            ("Profit Margin (%)", lambda: f"{kpis['Profit Margin (%)']:.1f}%"),
            ("Avg Cost per Shipment", lambda: fmt_currency(kpis["Avg Cost per Shipment"])),
            ("Avg Cost per Km", lambda: fmt_currency(kpis["Avg Cost per Km"])),
            ("Total Distance (km)", lambda: f"{kpis['Total Distance (km)']:,.0f} km"),
            ("Total Weight", lambda: f"{kpis['Total Weight']:,.0f}"),
            ("Avg Delivery Time (hrs)", lambda: f"{kpis['Avg Delivery Time (hrs)']:.1f} hrs"),
            ("Delay Rate (%)", lambda: f"{kpis['Delay Rate (%)']:.1f}%"),
            ("On-Time Rate (%)", lambda: f"{kpis['On-Time Rate (%)']:.1f}%"),
        ]
        kpi_list = [(label, getter()) for label, getter in kpi_order if label in kpis]

        charts = {}
        chart_details = {}

        if has(filtered_df, "month"):
            if has(filtered_df, "total_cost"):
                monthly_cost = filtered_df.groupby("month", as_index=False)["total_cost"].sum().sort_values("month")
                fig = px.bar(monthly_cost, x="month", y="total_cost", title="Monthly Logistics Cost",
                             color_discrete_sequence=[COLOR_SEQ[0]])
                fig.update_layout(xaxis_title="Month", yaxis_title="Total Cost ($)")
                charts["chart_monthly_cost"] = style_fig(fig, 380)

                tot = monthly_cost["total_cost"].sum()
                peak = monthly_cost.sort_values("total_cost", ascending=False).iloc[0]
                chart_details["chart_monthly_cost"] = (
                    f"Total expenditure across all tracked months stands at {fmt_currency(tot)}. "
                    f"Peak spending occurred in {peak['month']} at {fmt_currency(peak['total_cost'])}, "
                    f"indicating key seasonal volume spikes."
                )
            else:
                charts["chart_monthly_cost"] = empty_fig("Map a cost column to see the monthly cost trend")
                chart_details["chart_monthly_cost"] = "Map cost and date columns to track month-over-month expenditure fluctuations."

            if has(filtered_df, "profit"):
                monthly_profit = filtered_df.groupby("month", as_index=False)["profit"].sum().sort_values("month")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=monthly_profit["month"], y=monthly_profit["profit"], mode="lines+markers",
                                          name="Profit", line=dict(color=COLOR_SEQ[1], width=3), fill="tozeroy"))
                fig.update_layout(title="Monthly Profit", xaxis_title="Month", yaxis_title="Profit ($)")
                charts["chart_monthly_profit"] = style_fig(fig, 380)

                tot_p = monthly_profit["profit"].sum()
                peak_p = monthly_profit.sort_values("profit", ascending=False).iloc[0]
                chart_details["chart_monthly_profit"] = (
                    f"Cumulative profit over the period reaches {fmt_currency(tot_p)}. "
                    f"Peak net margin was recorded in {peak_p['month']} with {fmt_currency(peak_p['profit'])}, "
                    f"demonstrating strong revenue capture."
                )
            else:
                charts["chart_monthly_profit"] = empty_fig("Map revenue & cost columns to see the monthly profit trend")
                chart_details["chart_monthly_profit"] = "Map revenue and cost columns to track net profit and identify top margin months."

        present_cost_keys = [k for k in COST_LABELS if k in filtered_df.columns]
        if present_cost_keys:
            totals = {COST_LABELS[k]: filtered_df[k].sum() for k in present_cost_keys}
            fig = px.pie(names=list(totals.keys()), values=list(totals.values()), title="Cost Breakdown",
                         hole=0.55, color_discrete_sequence=COLOR_SEQ)
            charts["chart_cost_breakdown"] = style_fig(fig, 380)

            top_cat = max(totals, key=totals.get)
            sum_cost = sum(totals.values())
            pct = (totals[top_cat] / sum_cost * 100) if sum_cost else 0
            chart_details["chart_cost_breakdown"] = (
                f"{top_cat} represents the single largest expenditure category ({pct:.1f}% / {fmt_currency(totals[top_cat])}). "
                f"Optimizing top cost drivers will yield the highest direct savings."
            )
        else:
            charts["chart_cost_breakdown"] = empty_fig("Map cost component columns to see the cost breakdown")
            chart_details["chart_cost_breakdown"] = "Map individual cost components (Fuel, Transport, Warehouse, Labor) for breakdown insights."

        if has(filtered_df, "route", "total_cost"):
            route_cost = filtered_df.groupby("route", as_index=False)["total_cost"].sum().sort_values("total_cost", ascending=False).head(10)
            fig = px.bar(route_cost, x="total_cost", y="route", orientation="h", title="Top 10 Most Expensive Routes",
                         color="total_cost", color_continuous_scale=CONTINUOUS_SCALE)
            fig.update_layout(yaxis_title="", xaxis_title="Total Cost ($)", yaxis=dict(categoryorder="total ascending"))
            charts["chart_top_routes"] = style_fig(fig, 420)

            top_r = route_cost.iloc[0]
            chart_details["chart_top_routes"] = (
                f"Route '{top_r['route']}' generated the highest cost at {fmt_currency(top_r['total_cost'])}. "
                f"The top 10 routes comprise the primary freight expenditure across your transport network."
            )
        else:
            charts["chart_top_routes"] = empty_fig("Map route (or origin/destination) and cost columns to see top routes")
            chart_details["chart_top_routes"] = "Map route names or origin-destination pairs to highlight high-spend freight corridors."

        if has(filtered_df, "transport_mode"):
            mode_summary = filtered_df.groupby("transport_mode", as_index=False).size().rename(columns={"size": "shipments"})
            fig = px.bar(mode_summary, x="transport_mode", y="shipments", title="Shipments by Transport Mode",
                         color="transport_mode", color_discrete_sequence=COLOR_SEQ, text="shipments")
            fig.update_layout(xaxis_title="", yaxis_title="Shipments", showlegend=False)
            charts["chart_mode_shipments"] = style_fig(fig, 400)

            top_m = mode_summary.sort_values("shipments", ascending=False).iloc[0]
            chart_details["chart_mode_shipments"] = (
                f"'{top_m['transport_mode']}' is the most heavily utilized mode, handling {top_m['shipments']:,} shipments. "
                f"Balanced multi-modal routing can mitigate carrier capacity bottlenecks."
            )
        else:
            charts["chart_mode_shipments"] = empty_fig("Map a Transport Mode column to see shipments by mode")
            chart_details["chart_mode_shipments"] = "Map transport mode fields (Road, Air, Sea, Rail) to examine modal share."

        if has(filtered_df, "transport_mode", "total_cost"):
            mode_cost = filtered_df.groupby("transport_mode", as_index=False)["total_cost"].sum().sort_values("total_cost", ascending=False)
            fig = px.bar(mode_cost, x="transport_mode", y="total_cost", title="Cost by Transport Mode",
                         color="total_cost", color_continuous_scale=CONTINUOUS_SCALE)
            fig.update_layout(xaxis_title="", yaxis_title="Total Cost ($)")
            charts["chart_mode_cost"] = style_fig(fig, 400)

            top_mc = mode_cost.iloc[0]
            chart_details["chart_mode_cost"] = (
                f"'{top_mc['transport_mode']}' incurred the maximum total cost of {fmt_currency(top_mc['total_cost'])}. "
                f"Comparing cost per volume across modes highlights opportunities for intermodal shifting."
            )
        else:
            charts["chart_mode_cost"] = empty_fig("Map Transport Mode and cost columns to see cost by mode")
            chart_details["chart_mode_cost"] = "Map transport modes and costs to identify high-cost freight modalities."

        if has(filtered_df, "delivery_status"):
            status_counts = filtered_df["delivery_status"].value_counts().reset_index()
            status_counts.columns = ["delivery_status", "count"]
            fig = px.pie(status_counts, names="delivery_status", values="count", title="Delivery Status Distribution",
                         color="delivery_status", color_discrete_map=STATUS_COLORS, hole=0.55)
            charts["chart_delivery_status"] = style_fig(fig, 400)

            on_time_cnt = int(status_counts[status_counts["delivery_status"] == "On Time"]["count"].sum()) if "On Time" in status_counts["delivery_status"].values else 0
            on_time_pct = (on_time_cnt / len(filtered_df) * 100) if len(filtered_df) else 0
            chart_details["chart_delivery_status"] = (
                f"Overall network on-time performance stands at {on_time_pct:.1f}%. "
                f"Tracking status breakdown ensures early warning for SLA breaches and penalty risks."
            )
        else:
            charts["chart_delivery_status"] = empty_fig("Map a Delivery Status column (or planned/actual delivery time) to see delivery performance")
            chart_details["chart_delivery_status"] = "Map delivery status or delivery times to evaluate reliability and delay rates."

        chart_data = chart_payload(charts)

    ctx = base_context("home", full_df, filtered_df)
    ctx.update(
        source=source, meta=meta, preview_rows=preview_rows, preview_cols=preview_cols,
        mapping_groups=mapping_groups, has_upload=has_uploaded_data(sid),
        kpi_list=kpi_list, chart_data=chart_data, chart_details=chart_details,
    )
    return render_template("home.html", **ctx)


@app.route("/upload", methods=["POST"])
def upload():
    sid = get_session_id()
    file = request.files.get("file")
    if not file or not file.filename:
        return redirect(url_for("home"))

    raw_bytes = file.read()
    file.seek(0)
    fingerprint = f"{file.filename}-{len(raw_bytes)}"
    if get_upload_fingerprint(sid) != fingerprint:
        try:
            raw_df = load_uploaded_file(file)
        except Exception:
            return redirect(url_for("home"))
        meta = file_metadata(file.filename, raw_bytes, raw_df)
        suggested = suggest_mapping(raw_df.columns)
        set_raw_upload(sid, fingerprint, raw_df, meta, suggested)
    return redirect(url_for("home"))


@app.route("/confirm_mapping", methods=["POST"])
def confirm_mapping():
    sid = get_session_id()
    raw_df, meta, suggested = get_raw_upload(sid)
    if raw_df is None:
        return redirect(url_for("home"))

    mapping_inputs = {}
    for f in FIELDS:
        choice = request.form.get(f"map_{f.key}", "— None —")
        mapping_inputs[f.key] = None if choice == "— None —" else choice

    validation = validate_dataset(raw_df, mapping_inputs)
    if not validation["errors"]:
        mapped_df = apply_mapping(raw_df, mapping_inputs)
        cleaned_df = clean_dataset(mapped_df)
        final_df = derive_fields(cleaned_df)
        set_working_dataframe(sid, final_df, mapping_inputs)
    return redirect(url_for("home"))


@app.route("/discard_upload", methods=["POST"])
def discard():
    sid = get_session_id()
    discard_upload(sid)
    return redirect(url_for("home"))


# ---------------------------------------------------------------------------
# Cost Analysis
# ---------------------------------------------------------------------------
@app.route("/cost-analysis")
def cost_analysis():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    ctx = base_context("cost_analysis", full_df, df)

    if df.empty:
        return render_template("cost_analysis.html", **ctx, gate=None, empty=True)

    present_cost_keys = [k for k in COST_LABELS if k in df.columns]
    if not present_cost_keys and "total_cost" not in df.columns:
        return render_template("cost_analysis.html", **ctx, gate=(
            "No cost columns are mapped for this dataset. Go to the main Dashboard page and map at "
            "least one cost column to unlock this page."
        ))

    kpis = compute_kpis(df)
    kpi_list = []
    if "Total Logistics Cost" in kpis:
        kpi_list.append(("Total Logistics Cost", fmt_currency(kpis["Total Logistics Cost"])))
    if "Avg Cost per Shipment" in kpis:
        kpi_list.append(("Avg Cost / Shipment", fmt_currency(kpis["Avg Cost per Shipment"])))
    if "Avg Cost per Km" in kpis:
        kpi_list.append(("Avg Cost / Km", fmt_currency(kpis["Avg Cost per Km"])))
    if present_cost_keys and "total_cost" in df.columns and df["total_cost"].sum():
        top_component = max(present_cost_keys, key=lambda k: df[k].sum())
        share = df[top_component].sum() / df["total_cost"].sum() * 100
        kpi_list.append(("Top Cost Driver", f"{COST_LABELS[top_component]} ({share:.0f}%)"))

    charts = {}
    chart_details = {}

    if present_cost_keys:
        totals = {COST_LABELS[k]: df[k].sum() for k in present_cost_keys}
        totals_sorted = dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))
        fig = px.bar(x=list(totals_sorted.values()), y=list(totals_sorted.keys()), orientation="h",
                     title="Total Cost by Component", color=list(totals_sorted.keys()),
                     color_discrete_sequence=COLOR_SEQ)
        fig.update_layout(yaxis_title="", xaxis_title="Cost ($)", showlegend=False, yaxis=dict(categoryorder="total ascending"))
        charts["chart_cost_by_component"] = style_fig(fig)

        top_comp = list(totals_sorted.keys())[0]
        chart_details["chart_cost_by_component"] = (
            f"'{top_comp}' is the dominant cost element at {fmt_currency(totals_sorted[top_comp])}. "
            f"Consolidating vendor contracts in this area offers immediate bottom-line impact."
        )
    else:
        charts["chart_cost_by_component"] = empty_fig("Map individual cost components to see this breakdown")
        chart_details["chart_cost_by_component"] = "Map cost categories (Fuel, Transport, Warehouse) for detailed component analysis."

    if present_cost_keys and has(df, "month"):
        monthly_components = df.groupby("month", as_index=False)[present_cost_keys].sum().sort_values("month")
        fig2 = go.Figure()
        for i, k in enumerate(present_cost_keys):
            fig2.add_trace(go.Bar(x=monthly_components["month"], y=monthly_components[k],
                                   name=COST_LABELS[k], marker_color=COLOR_SEQ[i % len(COLOR_SEQ)]))
        fig2.update_layout(title="Monthly Cost Composition", barmode="stack", xaxis_title="Month", yaxis_title="Cost ($)")
        charts["chart_monthly_composition"] = style_fig(fig2)

        chart_details["chart_monthly_composition"] = (
            "Stacked view illustrates how expense composition shifts month-over-month. "
            "Sudden spikes in specific color blocks signal operational anomalies or rate hikes."
        )
    else:
        charts["chart_monthly_composition"] = empty_fig("Map a Date column and cost components to see the monthly composition")
        chart_details["chart_monthly_composition"] = "Map date and cost components to visualize month-by-month expense stacking."

    if has(df, "supplier", "total_cost"):
        by_supplier = df.groupby("supplier", as_index=False)["total_cost"].mean().sort_values("total_cost", ascending=False)
        fig3 = px.bar(by_supplier, x="total_cost", y="supplier", orientation="h",
                      title="Average Cost per Shipment by Supplier", color="total_cost",
                      color_continuous_scale=CONTINUOUS_SCALE)
        fig3.update_layout(yaxis=dict(categoryorder="total ascending"), yaxis_title="", xaxis_title="Avg Cost ($)")
        charts["chart_cost_by_supplier"] = style_fig(fig3, 420)

        top_sup = by_supplier.iloc[0]
        chart_details["chart_cost_by_supplier"] = (
            f"Supplier '{top_sup['supplier']}' posts the highest average cost per shipment ({fmt_currency(top_sup['total_cost'])}). "
            f"Benchmarking supplier rates helps negotiate competitive service level agreements."
        )
    else:
        charts["chart_cost_by_supplier"] = empty_fig("Map a Supplier and cost column to see cost by supplier")
        chart_details["chart_cost_by_supplier"] = "Map supplier names to compare average shipment costs across logistics partners."

    if has(df, "warehouse", "total_cost"):
        by_warehouse = df.groupby("warehouse", as_index=False)["total_cost"].mean().sort_values("total_cost", ascending=False)
        fig4 = px.bar(by_warehouse, x="total_cost", y="warehouse", orientation="h",
                      title="Average Cost per Shipment by Warehouse", color="total_cost",
                      color_continuous_scale=CONTINUOUS_SCALE)
        fig4.update_layout(height=420, yaxis_title="", xaxis_title="Avg Cost ($)", yaxis=dict(categoryorder="total ascending"))
        charts["chart_cost_by_warehouse"] = style_fig(fig4, 420)

        top_wh = by_warehouse.iloc[0]
        chart_details["chart_cost_by_warehouse"] = (
            f"Warehouse '{top_wh['warehouse']}' exhibits the highest average per-shipment handling cost at {fmt_currency(top_wh['total_cost'])}. "
            f"Cross-hub efficiency comparisons pinpoint facility optimization targets."
        )
    else:
        charts["chart_cost_by_warehouse"] = empty_fig("Map a Warehouse and cost column to see cost by warehouse")
        chart_details["chart_cost_by_warehouse"] = "Map warehouse facilities to evaluate fulfillment costs across storage hubs."

    if has(df, "distance_km", "total_cost"):
        color_col = "transport_mode" if "transport_mode" in df.columns else None
        fig5 = px.scatter(df, x="distance_km", y="total_cost", color=color_col, size="total_cost",
                           hover_data=[c for c in ["shipment_id", "supplier", "route"] if c in df.columns],
                           title="Cost vs Distance", color_discrete_sequence=COLOR_SEQ)
        fig5.update_layout(xaxis_title="Distance (km)", yaxis_title="Total Cost ($)")
        charts["chart_cost_vs_distance"] = style_fig(fig5, 460)

        chart_details["chart_cost_vs_distance"] = (
            "Scatter plot evaluates cost scaling against shipment distance. "
            "Outliers positioned high above the baseline indicate high cost per km routes needing audit."
        )
    else:
        charts["chart_cost_vs_distance"] = empty_fig("Map Distance and a cost column to see cost vs distance")
        chart_details["chart_cost_vs_distance"] = "Map distance and cost fields to uncover distance-to-cost scaling efficiency."

    top10_cols = [c for c in [
        "shipment_id", "date", "supplier", "warehouse", "route", "transport_mode", "distance_km",
    ] + present_cost_keys + ["total_cost", "cost_per_km"] if c in df.columns]
    top10 = None
    if "total_cost" in df.columns:
        top10_df = df[top10_cols].sort_values("total_cost", ascending=False).head(10).copy()
        top10 = table_to_rows(top10_df)

    ctx.update(kpi_list=kpi_list, chart_data=chart_payload(charts), chart_details=chart_details, top10=top10,
                top10_cols=[COST_LABELS.get(c, c.replace("_", " ").title()) for c in top10_cols] if top10 else [])
    return render_template("cost_analysis.html", **ctx, gate=None, empty=False)


# ---------------------------------------------------------------------------
# Route Analysis
# ---------------------------------------------------------------------------
@app.route("/route-analysis")
def route_analysis():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    ctx = base_context("route_analysis", full_df, df)

    if df.empty:
        return render_template("route_analysis.html", **ctx, gate=None, empty=True)
    if "route" not in df.columns:
        return render_template("route_analysis.html", **ctx, gate=(
            "No Route, Origin, or Destination columns are mapped for this dataset."
        ))

    agg = {"shipments": ("route", "count")}
    if "total_cost" in df.columns:
        agg["total_cost"] = ("total_cost", "sum")
    if "revenue" in df.columns:
        agg["total_revenue"] = ("revenue", "sum")
    if "profit" in df.columns:
        agg["total_profit"] = ("profit", "sum")
    if "distance_km" in df.columns:
        agg["avg_distance"] = ("distance_km", "mean")
    if "cost_per_km" in df.columns:
        agg["avg_cost_per_km"] = ("cost_per_km", "mean")
    if "delivery_time_hours" in df.columns:
        agg["avg_delivery_time"] = ("delivery_time_hours", "mean")
    if "is_delayed" in df.columns:
        agg["delay_rate"] = ("is_delayed", "mean")

    route_summary = df.groupby("route", as_index=False).agg(**agg)
    sort_key = "total_cost" if "total_cost" in route_summary.columns else "shipments"
    route_summary = route_summary.sort_values(sort_key, ascending=False)

    kpi_list = [("Total Routes", f"{df['route'].nunique():,}")]
    if "total_cost" in route_summary.columns:
        kpi_list.append(("Most Expensive Route", route_summary.iloc[0]["route"]))
    if "total_profit" in route_summary.columns:
        best_route = route_summary.sort_values("total_profit", ascending=False).iloc[0]
        kpi_list.append(("Most Profitable Route", best_route["route"]))
    if "avg_distance" in route_summary.columns:
        kpi_list.append(("Avg Distance / Route", f"{route_summary['avg_distance'].mean():.0f} km"))

    charts = {}
    chart_details = {}

    if "total_cost" in route_summary.columns:
        top_cost = route_summary.head(12)
        fig1 = px.bar(top_cost, x="total_cost", y="route", orientation="h", title="Top 12 Routes by Total Cost",
                      color="total_cost", color_continuous_scale=CONTINUOUS_SCALE)
        fig1.update_layout(yaxis=dict(categoryorder="total ascending"), yaxis_title="", xaxis_title="Total Cost ($)")
        charts["chart_top_cost_routes"] = style_fig(fig1, 460)

        highest = top_cost.iloc[0]
        chart_details["chart_top_cost_routes"] = (
            f"The highest spend freight corridor is '{highest['route']}' ({fmt_currency(highest['total_cost'])}). "
            f"Route consolidation and batch dispatch on this lane can drive substantial savings."
        )
    else:
        charts["chart_top_cost_routes"] = empty_fig("Map a cost column to see top routes by cost")
        chart_details["chart_top_cost_routes"] = "Map cost columns to analyze expenditure across shipping routes."

    if "total_profit" in route_summary.columns:
        top_profit = route_summary.sort_values("total_profit", ascending=False).head(12)
        fig2 = px.bar(top_profit, x="total_profit", y="route", orientation="h", title="Top 12 Routes by Total Profit",
                      color="total_profit", color_continuous_scale=CONTINUOUS_SCALE_DIVERGING)
        fig2.update_layout(yaxis=dict(categoryorder="total ascending"), yaxis_title="", xaxis_title="Total Profit ($)")
        charts["chart_top_profit_routes"] = style_fig(fig2, 460)

        best_p = top_profit.iloc[0]
        chart_details["chart_top_profit_routes"] = (
            f"'{best_p['route']}' generated the maximum net profit of {fmt_currency(best_p['total_profit'])}. "
            f"Promoting high-margin freight corridors optimizes net operating margin."
        )
    else:
        charts["chart_top_profit_routes"] = empty_fig("Map revenue and cost columns to see top routes by profit")
        chart_details["chart_top_profit_routes"] = "Map revenue and cost columns to identify top profitable transit lanes."

    if {"avg_distance", "avg_cost_per_km"}.issubset(route_summary.columns):
        fig3 = px.scatter(route_summary, x="avg_distance", y="avg_cost_per_km", size="shipments",
                           color="total_profit" if "total_profit" in route_summary.columns else "shipments",
                           hover_name="route", title="Cost Efficiency: Distance vs Cost/Km",
                           color_continuous_scale=CONTINUOUS_SCALE_DIVERGING)
        fig3.update_layout(xaxis_title="Avg Distance (km)", yaxis_title="Avg Cost per Km ($)")
        charts["chart_route_efficiency"] = style_fig(fig3, 440)

        chart_details["chart_route_efficiency"] = (
            "Compares route length against cost per km efficiency. "
            "Points in the upper-left quadrant represent short, expensive lanes ideal for modal optimization."
        )
    else:
        charts["chart_route_efficiency"] = empty_fig("Map Distance and a cost column to see route efficiency")
        chart_details["chart_route_efficiency"] = "Map distance and cost fields to examine per-kilometer transit efficiency."

    if "avg_delivery_time" in route_summary.columns:
        slow_df = route_summary.sort_values("avg_delivery_time", ascending=False).head(12)
        fig4 = px.bar(slow_df, x="avg_delivery_time", y="route", orientation="h",
                      title="Slowest 12 Routes by Avg Delivery Time", color="avg_delivery_time",
                      color_continuous_scale="Oranges")
        fig4.update_layout(yaxis=dict(categoryorder="total ascending"), yaxis_title="", xaxis_title="Avg Delivery Time (hrs)")
        charts["chart_slowest_routes"] = style_fig(fig4, 440)

        slowest = slow_df.iloc[0]
        chart_details["chart_slowest_routes"] = (
            f"'{slowest['route']}' experiences the longest lead time ({slowest['avg_delivery_time']:.1f} hrs). "
            f"Investigating transit bottlenecks on this route can help improve delivery SLAs."
        )
    else:
        charts["chart_slowest_routes"] = empty_fig("Map a Delivery Time column to see the slowest routes")
        chart_details["chart_slowest_routes"] = "Map delivery duration to identify slow routes and lead time variance."

    if has(df, "destination"):
        agg2 = {"shipments": ("destination", "count")}
        if "revenue" in df.columns:
            agg2["total_revenue"] = ("revenue", "sum")
        dest_summary = df.groupby("destination", as_index=False).agg(**agg2).sort_values("shipments", ascending=False)
        fig5 = px.treemap(dest_summary, path=["destination"], values="shipments",
                           color="total_revenue" if "total_revenue" in dest_summary.columns else "shipments",
                           color_continuous_scale=CONTINUOUS_SCALE, title="Shipment Volume by Destination")
        charts["chart_destination_volume"] = style_fig(fig5, 460)

        top_dest = dest_summary.iloc[0]
        chart_details["chart_destination_volume"] = (
            f"'{top_dest['destination']}' receives the highest volume ({top_dest['shipments']:,} shipments). "
            f"Treemap sizing reflects relative destination demand concentration across regional hubs."
        )

    fmt_map = {}
    for c in ["total_cost", "total_revenue", "total_profit"]:
        if c in route_summary.columns:
            route_summary[c] = route_summary[c].map(lambda x: f"${x:,.2f}")
    if "avg_distance" in route_summary.columns:
        route_summary["avg_distance"] = route_summary["avg_distance"].map(lambda x: f"{x:.1f}")
    if "avg_cost_per_km" in route_summary.columns:
        route_summary["avg_cost_per_km"] = route_summary["avg_cost_per_km"].map(lambda x: f"${x:.2f}")
    if "avg_delivery_time" in route_summary.columns:
        route_summary["avg_delivery_time"] = route_summary["avg_delivery_time"].map(lambda x: f"{x:.1f}")
    if "delay_rate" in route_summary.columns:
        route_summary["delay_rate"] = route_summary["delay_rate"].map(lambda x: f"{x * 100:.1f}%")

    table_cols = [c.replace("_", " ").title() for c in route_summary.columns]
    ctx.update(kpi_list=kpi_list, chart_data=chart_payload(charts), chart_details=chart_details,
                table_cols=table_cols, table_rows=route_summary.values.tolist())
    return render_template("route_analysis.html", **ctx, gate=None, empty=False)


# ---------------------------------------------------------------------------
# Vehicle Analysis
# ---------------------------------------------------------------------------
@app.route("/vehicle-analysis")
def vehicle_analysis():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    ctx = base_context("vehicle_analysis", full_df, df)

    if df.empty:
        return render_template("vehicle_analysis.html", **ctx, gate=None, empty=True)

    vehicle_key = "vehicle" if has(df, "vehicle") else ("transport_mode" if has(df, "transport_mode") else None)
    if vehicle_key is None:
        return render_template("vehicle_analysis.html", **ctx, gate=(
            "No Vehicle or Transport Mode column is mapped for this dataset."
        ))

    agg = {"shipments": (vehicle_key, "count")}
    if "distance_km" in df.columns:
        agg["total_distance"] = ("distance_km", "sum")
    if "total_cost" in df.columns:
        agg["total_cost"] = ("total_cost", "sum")
    if "fuel_cost" in df.columns:
        agg["total_fuel"] = ("fuel_cost", "sum")
    if "revenue" in df.columns:
        agg["total_revenue"] = ("revenue", "sum")
    if "profit" in df.columns:
        agg["total_profit"] = ("profit", "sum")
    if "maintenance_cost" in df.columns:
        agg["avg_maintenance"] = ("maintenance_cost", "mean")

    vehicle_summary = df.groupby(vehicle_key, as_index=False).agg(**agg).sort_values("shipments", ascending=False)

    kpi_list = [("Vehicles / Modes", f"{df[vehicle_key].nunique():,}"),
                ("Most Used", vehicle_summary.iloc[0][vehicle_key])]
    if "total_cost" in vehicle_summary.columns:
        best_perf = vehicle_summary.sort_values("total_cost").iloc[0]
        kpi_list.append(("Lowest Total Cost", best_perf[vehicle_key]))
        worst_perf = vehicle_summary.sort_values("total_cost", ascending=False).iloc[0]
        kpi_list.append(("Highest Total Cost", worst_perf[vehicle_key]))

    charts = {}
    chart_details = {}

    fig1 = px.bar(vehicle_summary, x="shipments", y=vehicle_key, orientation="h", title="Shipments by Vehicle",
                  color=vehicle_key, color_discrete_sequence=COLOR_SEQ, text="shipments")
    fig1.update_layout(yaxis_title="", xaxis_title="Shipments", showlegend=False, yaxis=dict(categoryorder="total ascending"))
    charts["chart_vehicle_shipments"] = style_fig(fig1)

    top_v = vehicle_summary.iloc[0]
    chart_details["chart_vehicle_shipments"] = (
        f"'{top_v[vehicle_key]}' handled the most volume ({top_v['shipments']:,} shipments). "
        f"Fleet utilization charts assist in balancing asset assignment and preventing idle equipment."
    )

    if "total_distance" in vehicle_summary.columns:
        fig2 = px.bar(vehicle_summary.sort_values("total_distance", ascending=False), x="total_distance", y=vehicle_key,
                      orientation="h", title="Total Distance by Vehicle", color=vehicle_key, color_discrete_sequence=COLOR_SEQ)
        fig2.update_layout(yaxis_title="", xaxis_title="Distance (km)", showlegend=False, yaxis=dict(categoryorder="total ascending"))
        charts["chart_vehicle_distance"] = style_fig(fig2)

        top_d = vehicle_summary.sort_values("total_distance", ascending=False).iloc[0]
        chart_details["chart_vehicle_distance"] = (
            f"'{top_d[vehicle_key]}' logged the longest total distance ({top_d['total_distance']:,.0f} km). "
            f"High kilometer usage indicates heavy wear and necessity for scheduled maintenance checks."
        )
    else:
        charts["chart_vehicle_distance"] = empty_fig("Map a Distance column to see distance by vehicle")
        chart_details["chart_vehicle_distance"] = "Map distance fields to analyze fleet mileage distribution."

    if "total_fuel" in vehicle_summary.columns:
        fig3 = px.bar(vehicle_summary.sort_values("total_fuel", ascending=False), x="total_fuel", y=vehicle_key,
                      orientation="h", title="Fuel Cost by Vehicle", color="total_fuel", color_continuous_scale=CONTINUOUS_SCALE)
        fig3.update_layout(yaxis_title="", xaxis_title="Fuel Cost ($)", yaxis=dict(categoryorder="total ascending"))
        charts["chart_vehicle_cost"] = style_fig(fig3)

        top_f = vehicle_summary.sort_values("total_fuel", ascending=False).iloc[0]
        chart_details["chart_vehicle_cost"] = (
            f"'{top_f[vehicle_key]}' consumed the highest fuel budget ({fmt_currency(top_f['total_fuel'])}). "
            f"Monitoring fuel burn rates aids in eco-routing and fleet electrification decisions."
        )
    elif "total_cost" in vehicle_summary.columns:
        fig3 = px.bar(vehicle_summary.sort_values("total_cost", ascending=False), x="total_cost", y=vehicle_key,
                      orientation="h", title="Total Cost by Vehicle", color="total_cost", color_continuous_scale=CONTINUOUS_SCALE)
        fig3.update_layout(yaxis_title="", xaxis_title="Total Cost ($)", yaxis=dict(categoryorder="total ascending"))
        charts["chart_vehicle_cost"] = style_fig(fig3)

        top_c = vehicle_summary.sort_values("total_cost", ascending=False).iloc[0]
        chart_details["chart_vehicle_cost"] = (
            f"'{top_c[vehicle_key]}' accumulated the highest total operating cost ({fmt_currency(top_c['total_cost'])})."
        )
    else:
        charts["chart_vehicle_cost"] = empty_fig("Map a Fuel Cost or Total Cost column")
        chart_details["chart_vehicle_cost"] = "Map fuel or total cost columns to inspect vehicle operating expenses."

    if "total_revenue" in vehicle_summary.columns and "total_profit" in vehicle_summary.columns:
        fig4 = px.bar(vehicle_summary.sort_values("total_profit", ascending=False), x="total_profit", y=vehicle_key,
                      orientation="h", title="Profit by Vehicle", color="total_profit", color_continuous_scale=CONTINUOUS_SCALE_DIVERGING)
        fig4.update_layout(yaxis_title="", xaxis_title="Profit ($)", yaxis=dict(categoryorder="total ascending"))
        charts["chart_vehicle_profit"] = style_fig(fig4)

        top_vp = vehicle_summary.sort_values("total_profit", ascending=False).iloc[0]
        chart_details["chart_vehicle_profit"] = (
            f"'{top_vp[vehicle_key]}' generated net profit of {fmt_currency(top_vp['total_profit'])}. "
            f"Fleet contribution margin analysis guides capital expenditure allocations."
        )
    elif "cost_per_km" in df.columns:
        fig4 = px.box(df, x=vehicle_key, y="cost_per_km", title="Cost per Km Distribution by Vehicle",
                      color=vehicle_key, color_discrete_sequence=COLOR_SEQ)
        fig4.update_layout(xaxis_title="", yaxis_title="Cost per Km ($)", showlegend=False)
        charts["chart_vehicle_profit"] = style_fig(fig4)

        chart_details["chart_vehicle_profit"] = (
            "Boxplot distribution shows per-kilometer cost variability across vehicle types. "
            "Narrow boxes indicate predictable maintenance and fuel efficiency."
        )
    else:
        charts["chart_vehicle_profit"] = empty_fig("Map Revenue and cost columns to see profit by vehicle")
        chart_details["chart_vehicle_profit"] = "Map revenue and cost fields to examine profitability across vehicles."

    driver_section = False
    if has(df, "driver"):
        driver_section = True
        agg_d = {"shipments": ("driver", "count")}
        if "delivery_time_hours" in df.columns:
            agg_d["avg_delivery_time"] = ("delivery_time_hours", "mean")
        if "is_delayed" in df.columns:
            agg_d["on_time_pct"] = ("is_delayed", lambda s: (1 - s.mean()) * 100)
        driver_summary = df.groupby("driver", as_index=False).agg(**agg_d).sort_values("shipments", ascending=False)

        top_d_df = driver_summary.head(10)
        fig5 = px.bar(top_d_df, x="shipments", y="driver", orientation="h", title="Top 10 Drivers by Shipment Count",
                      color="shipments", color_continuous_scale=CONTINUOUS_SCALE)
        fig5.update_layout(yaxis_title="", xaxis_title="Shipments", yaxis=dict(categoryorder="total ascending"))
        charts["chart_driver_shipments"] = style_fig(fig5, 420)

        top_drv = top_d_df.iloc[0]
        chart_details["chart_driver_shipments"] = (
            f"Driver '{top_drv['driver']}' completed the most shipments ({top_drv['shipments']:,}). "
            f"Recognizing top performers supports driver retention and safety incentive programs."
        )

        if {"avg_delivery_time", "on_time_pct"}.issubset(driver_summary.columns):
            fig6 = px.scatter(driver_summary, x="avg_delivery_time", y="on_time_pct", size="shipments",
                               color="on_time_pct", hover_name="driver",
                               title="Driver On-Time Rate vs Avg Delivery Time", color_continuous_scale=CONTINUOUS_SCALE_DIVERGING)
            fig6.update_layout(xaxis_title="Avg Delivery Time (hrs)", yaxis_title="On-Time Rate (%)")
            charts["chart_driver_ontime"] = style_fig(fig6, 420)

            chart_details["chart_driver_ontime"] = (
                "Plots driver timeliness against average transit time. "
                "Drivers in the upper-left corner achieve fast turnaround times with superior SLA compliance."
            )
        else:
            charts["chart_driver_ontime"] = empty_fig("Map Delivery Time and Delivery Status to see driver on-time rate")
            chart_details["chart_driver_ontime"] = "Map delivery duration and status to evaluate driver timeliness."

    for c in ["total_cost", "total_fuel", "total_revenue", "total_profit", "avg_maintenance"]:
        if c in vehicle_summary.columns:
            vehicle_summary[c] = vehicle_summary[c].map(lambda x: f"${x:,.2f}")
    if "total_distance" in vehicle_summary.columns:
        vehicle_summary["total_distance"] = vehicle_summary["total_distance"].map(lambda x: f"{x:,.0f}")

    table_cols = [c.replace("_", " ").title() for c in vehicle_summary.columns]
    ctx.update(kpi_list=kpi_list, chart_data=chart_payload(charts), chart_details=chart_details, driver_section=driver_section,
                table_cols=table_cols, table_rows=vehicle_summary.values.tolist())
    return render_template("vehicle_analysis.html", **ctx, gate=None, empty=False)


# ---------------------------------------------------------------------------
# Warehouse Analysis
# ---------------------------------------------------------------------------
@app.route("/warehouse-analysis")
def warehouse_analysis():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    ctx = base_context("warehouse_analysis", full_df, df)

    if df.empty:
        return render_template("warehouse_analysis.html", **ctx, gate=None, empty=True)
    if not has(df, "warehouse"):
        return render_template("warehouse_analysis.html", **ctx, gate=(
            "No Warehouse column is mapped for this dataset."
        ))

    agg = {"shipments": ("warehouse", "count")}
    if "warehouse_cost" in df.columns:
        agg["total_warehouse_cost"] = ("warehouse_cost", "sum")
    if "total_cost" in df.columns:
        agg["total_cost"] = ("total_cost", "sum")
    if "revenue" in df.columns:
        agg["total_revenue"] = ("revenue", "sum")
    if "profit" in df.columns:
        agg["total_profit"] = ("profit", "sum")
    if "delivery_time_hours" in df.columns:
        agg["avg_delivery_time"] = ("delivery_time_hours", "mean")

    wh_summary = df.groupby("warehouse", as_index=False).agg(**agg).sort_values("shipments", ascending=False)

    kpi_list = [("Warehouses", f"{df['warehouse'].nunique():,}")]
    if "total_warehouse_cost" in wh_summary.columns:
        kpi_list.append(("Total Warehouse Cost", fmt_currency(wh_summary["total_warehouse_cost"].sum())))
    elif "total_cost" in wh_summary.columns:
        kpi_list.append(("Total Logistics Cost", fmt_currency(wh_summary["total_cost"].sum())))
    if "total_profit" in wh_summary.columns:
        best = wh_summary.sort_values("total_profit", ascending=False).iloc[0]
        kpi_list.append(("Most Profitable Warehouse", best["warehouse"]))
    busiest = wh_summary.sort_values("shipments", ascending=False).iloc[0]
    kpi_list.append(("Busiest Warehouse", busiest["warehouse"]))

    charts = {}
    chart_details = {}

    cost_col = "total_warehouse_cost" if "total_warehouse_cost" in wh_summary.columns else (
        "total_cost" if "total_cost" in wh_summary.columns else None)
    if cost_col:
        sorted_wh = wh_summary.sort_values(cost_col, ascending=False)
        fig1 = px.bar(sorted_wh, x=cost_col, y="warehouse", orientation="h",
                      title="Warehouse Cost" if cost_col == "total_warehouse_cost" else "Total Logistics Cost by Warehouse",
                      color=cost_col, color_continuous_scale=CONTINUOUS_SCALE)
        fig1.update_layout(yaxis_title="", xaxis_title="Cost ($)", yaxis=dict(categoryorder="total ascending"))
        charts["chart_warehouse_cost"] = style_fig(fig1)

        top_w = sorted_wh.iloc[0]
        chart_details["chart_warehouse_cost"] = (
            f"Warehouse '{top_w['warehouse']}' generated the highest storage spend ({fmt_currency(top_w[cost_col])}). "
            f"Benchmarking handling costs per unit across sites highlights operational savings."
        )
    else:
        charts["chart_warehouse_cost"] = empty_fig("Map a Warehouse Cost or Total Cost column")
        chart_details["chart_warehouse_cost"] = "Map warehouse storage or total cost columns for fulfillment cost comparisons."

    vol_wh = wh_summary.sort_values("shipments", ascending=False)
    fig2 = px.bar(vol_wh, x="shipments", y="warehouse", orientation="h",
                  title="Shipment Volume by Warehouse", color="shipments", color_continuous_scale=CONTINUOUS_SCALE)
    fig2.update_layout(yaxis_title="", xaxis_title="Shipments", yaxis=dict(categoryorder="total ascending"))
    charts["chart_warehouse_volume"] = style_fig(fig2)

    top_v_wh = vol_wh.iloc[0]
    chart_details["chart_warehouse_volume"] = (
        f"'{top_v_wh['warehouse']}' is the busiest fulfillment hub, dispatching {top_v_wh['shipments']:,} shipments. "
        f"Volume metrics assist facility managers in throughput and labor scheduling."
    )

    if "avg_delivery_time" in wh_summary.columns:
        del_wh = wh_summary.sort_values("avg_delivery_time")
        fig3 = px.bar(del_wh, x="avg_delivery_time", y="warehouse", orientation="h",
                      title="Average Delivery Time by Warehouse", color="avg_delivery_time",
                      color_continuous_scale="Oranges")
        fig3.update_layout(yaxis_title="", xaxis_title="Avg Delivery Time (hrs)", yaxis=dict(categoryorder="total ascending"))
        charts["chart_warehouse_delivery"] = style_fig(fig3)

        fast_wh = del_wh.iloc[0]
        chart_details["chart_warehouse_delivery"] = (
            f"'{fast_wh['warehouse']}' achieved the fastest average dispatch time ({fast_wh['avg_delivery_time']:.1f} hrs). "
            f"Faster warehouse processing directly improves overall end-to-end order SLAs."
        )
    else:
        charts["chart_warehouse_delivery"] = empty_fig("Map a Delivery Time column to see average storage/delivery time")
        chart_details["chart_warehouse_delivery"] = "Map delivery duration to evaluate warehouse turnaround and fulfillment speed."

    if "total_profit" in wh_summary.columns:
        prof_wh = wh_summary.sort_values("total_profit", ascending=False)
        fig4 = px.bar(prof_wh, x="total_profit", y="warehouse", orientation="h",
                      title="Profit by Warehouse", color="total_profit", color_continuous_scale=CONTINUOUS_SCALE_DIVERGING)
        fig4.update_layout(yaxis_title="", xaxis_title="Profit ($)", yaxis=dict(categoryorder="total ascending"))
        charts["chart_warehouse_profit"] = style_fig(fig4)

        best_wh_p = prof_wh.iloc[0]
        chart_details["chart_warehouse_profit"] = (
            f"'{best_wh_p['warehouse']}' delivered highest net profit ({fmt_currency(best_wh_p['total_profit'])}). "
            f"Profitable facility identification informs regional inventory allocation."
        )
    else:
        charts["chart_warehouse_profit"] = empty_fig("Map Revenue and cost columns to see profit by warehouse")
        chart_details["chart_warehouse_profit"] = "Map revenue and costs to compare net profit generated by fulfillment center."

    for c in ["total_warehouse_cost", "total_cost", "total_revenue", "total_profit"]:
        if c in wh_summary.columns:
            wh_summary[c] = wh_summary[c].map(lambda x: f"${x:,.2f}")
    if "avg_delivery_time" in wh_summary.columns:
        wh_summary["avg_delivery_time"] = wh_summary["avg_delivery_time"].map(lambda x: f"{x:.1f}")

    table_cols = [c.replace("_", " ").title() for c in wh_summary.columns]
    ctx.update(kpi_list=kpi_list, chart_data=chart_payload(charts), chart_details=chart_details,
                table_cols=table_cols, table_rows=wh_summary.values.tolist())
    return render_template("warehouse_analysis.html", **ctx, gate=None, empty=False)


# ---------------------------------------------------------------------------
# Delay Analysis
# ---------------------------------------------------------------------------
@app.route("/delay-analysis")
def delay_analysis():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    ctx = base_context("delay_analysis", full_df, df)

    if df.empty:
        return render_template("delay_analysis.html", **ctx, gate=None, empty=True)
    if not has(df, "is_delayed"):
        return render_template("delay_analysis.html", **ctx, gate=(
            "No Delivery Status (or Planned/Actual Delivery Time) columns are mapped for this dataset."
        ))

    delay_rate = df["is_delayed"].mean() * 100
    delayed_count = int(df["is_delayed"].sum())

    kpi_list = [
        ("Delay Rate", f"{delay_rate:.1f}%"),
        ("Delayed Shipments", f"{delayed_count:,}"),
        ("On-Time Shipments", f"{len(df) - delayed_count:,}"),
    ]
    if has(df, "delivery_time_hours"):
        kpi_list.append(("Avg Delivery Time", f"{df['delivery_time_hours'].mean():.1f} hrs"))

    charts = {}
    chart_details = {}

    if has(df, "delivery_status"):
        status_counts = df["delivery_status"].value_counts().reset_index()
        status_counts.columns = ["delivery_status", "count"]
        fig1 = px.pie(status_counts, names="delivery_status", values="count", title="Delivery Status Distribution",
                      color="delivery_status", color_discrete_map=STATUS_COLORS, hole=0.55)
        charts["chart_status_distribution"] = style_fig(fig1)

        chart_details["chart_status_distribution"] = (
            f"Overall delay rate across the network is {delay_rate:.1f}%. "
            f"Donut chart shows the proportion of On Time vs Delayed vs Cancelled orders."
        )
    else:
        fig1 = px.pie(names=["Delayed", "On Time"], values=[delayed_count, len(df) - delayed_count],
                      title="Delayed vs On Time", color_discrete_sequence=["#EF4444", "#10B981"], hole=0.55)
        charts["chart_status_distribution"] = style_fig(fig1)

        chart_details["chart_status_distribution"] = (
            f"{delayed_count:,} out of {len(df):,} total shipments experienced delays ({delay_rate:.1f}% delay rate)."
        )

    if has(df, "month"):
        monthly_delay = df.groupby("month", as_index=False)["is_delayed"].mean().sort_values("month")
        monthly_delay["is_delayed"] = monthly_delay["is_delayed"] * 100
        fig2 = px.line(monthly_delay, x="month", y="is_delayed", title="Delay Rate Trend", markers=True,
                       color_discrete_sequence=["#EF4444"])
        fig2.update_layout(xaxis_title="Month", yaxis_title="Delay Rate (%)")
        charts["chart_delay_trend"] = style_fig(fig2)

        peak_d = monthly_delay.sort_values("is_delayed", ascending=False).iloc[0]
        chart_details["chart_delay_trend"] = (
            f"Delay rate peaked in {peak_d['month']} at {peak_d['is_delayed']:.1f}%. "
            f"Monthly trend lines reveal whether operational corrective actions are reducing delays over time."
        )
    else:
        charts["chart_delay_trend"] = empty_fig("Map a Date column to see the delay trend")
        chart_details["chart_delay_trend"] = "Map date fields to track delay percentage progression over months."

    if has(df, "route"):
        route_delay = df.groupby("route", as_index=False)["is_delayed"].mean().sort_values("is_delayed", ascending=False).head(12)
        route_delay["is_delayed"] = route_delay["is_delayed"] * 100
        fig3 = px.bar(route_delay, x="is_delayed", y="route", orientation="h", title="Top 12 Routes by Delay Rate",
                      color="is_delayed", color_continuous_scale="Oranges")
        fig3.update_layout(yaxis=dict(categoryorder="total ascending"), yaxis_title="", xaxis_title="Delay Rate (%)")
        charts["chart_route_delay"] = style_fig(fig3, 440)

        worst_rd = route_delay.iloc[0]
        chart_details["chart_route_delay"] = (
            f"Route '{worst_rd['route']}' registered highest delay rate ({worst_rd['is_delayed']:.1f}%). "
            f"Targeting schedule buffers on high-delay routes protects customer SLA compliance."
        )
    else:
        charts["chart_route_delay"] = empty_fig("Map a Route (or Origin/Destination) column to see delay by route")
        chart_details["chart_route_delay"] = "Map route names to identify bottleneck freight corridors."

    mode_key = "transport_mode" if "transport_mode" in df.columns else ("vehicle" if "vehicle" in df.columns else None)
    if mode_key:
        mode_delay = df.groupby(mode_key, as_index=False)["is_delayed"].mean().sort_values("is_delayed", ascending=False)
        mode_delay["is_delayed"] = mode_delay["is_delayed"] * 100
        fig4 = px.bar(mode_delay, x="is_delayed", y=mode_key, orientation="h", title="Delay Rate by Transport Mode",
                      color="is_delayed", color_continuous_scale="Oranges")
        fig4.update_layout(yaxis_title="", xaxis_title="Delay Rate (%)", yaxis=dict(categoryorder="total ascending"))
        charts["chart_mode_delay"] = style_fig(fig4, 440)

        worst_md = mode_delay.iloc[0]
        chart_details["chart_mode_delay"] = (
            f"'{worst_md[mode_key]}' experienced the highest delay incidence ({worst_md['is_delayed']:.1f}%). "
            f"Comparing mode delay rates helps re-route time-sensitive freight onto more reliable modes."
        )
    else:
        charts["chart_mode_delay"] = empty_fig("Map a Transport Mode or Vehicle column to see delay by mode")
        chart_details["chart_mode_delay"] = "Map transport modes to evaluate carrier performance reliability."

    display_cols = [c for c in ["shipment_id", "date", "route", "transport_mode", "vehicle",
                                 "delivery_time_hours", "planned_delivery_time_hours", "delivery_status"]
                    if c in df.columns]
    delayed_df = df[df["is_delayed"]][display_cols]
    table_rows = table_to_rows(delayed_df) if not delayed_df.empty else []
    table_cols = [c.replace("_", " ").title() for c in display_cols]

    ctx.update(kpi_list=kpi_list, chart_data=chart_payload(charts), chart_details=chart_details,
                table_cols=table_cols, table_rows=table_rows)
    return render_template("delay_analysis.html", **ctx, gate=None, empty=False)


# ---------------------------------------------------------------------------
# Profitability Analysis
# ---------------------------------------------------------------------------
@app.route("/profitability-analysis")
def profitability_analysis():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    ctx = base_context("profitability_analysis", full_df, df)

    if df.empty:
        return render_template("profitability_analysis.html", **ctx, gate=None, empty=True)
    if not has(df, "revenue") or not has(df, "total_cost"):
        return render_template("profitability_analysis.html", **ctx, gate=(
            "Map both a Revenue column and at least one cost column on the main Dashboard page."
        ))

    kpis = compute_kpis(df)
    kpi_list = [("Total Profit", fmt_currency(kpis.get("Total Profit", 0)))]
    if "Profit Margin (%)" in kpis:
        kpi_list.append(("Profit Margin", f"{kpis['Profit Margin (%)']:.1f}%"))
    profitable_pct = (df["profit"] > 0).mean() * 100
    kpi_list.append(("Profitable Shipments", f"{profitable_pct:.1f}%"))
    loss_making = (df["profit"] < 0).sum()
    kpi_list.append(("Loss-Making Shipments", f"{loss_making:,}"))

    charts = {}
    chart_details = {}

    if has(df, "month"):
        monthly = df.groupby("month", as_index=False).agg(
            revenue=("revenue", "sum"), cost=("total_cost", "sum"), profit=("profit", "sum")
        ).sort_values("month")
        fig1 = go.Figure()
        fig1.add_trace(go.Bar(x=monthly["month"], y=monthly["revenue"], name="Revenue", marker_color="#3B82F6"))
        fig1.add_trace(go.Bar(x=monthly["month"], y=monthly["cost"], name="Cost", marker_color="#64748B"))
        fig1.add_trace(go.Scatter(x=monthly["month"], y=monthly["profit"], name="Profit",
                                   mode="lines+markers", line=dict(color="#10B981", width=3), yaxis="y2"))
        fig1.update_layout(title="Revenue vs Cost vs Profit (Monthly)", barmode="group",
                            yaxis=dict(title="Revenue / Cost ($)"),
                            yaxis2=dict(title="Profit ($)", overlaying="y", side="right"))
        charts["chart_rev_cost_profit"] = style_fig(fig1, 440)

        chart_details["chart_rev_cost_profit"] = (
            "Dual-axis chart displays revenue and cost bars alongside the net profit trajectory. "
            "Widening gaps between blue revenue and gray cost bars indicate margin expansion."
        )
    else:
        charts["chart_rev_cost_profit"] = empty_fig("Map a Date column to see monthly profitability trends")
        chart_details["chart_rev_cost_profit"] = "Map date, revenue, and cost fields to track monthly gross margin trends."

    if has(df, "month", "profit_margin_pct"):
        margin_monthly = df.groupby("month", as_index=False)["profit_margin_pct"].mean().sort_values("month")
        fig2 = px.area(margin_monthly, x="month", y="profit_margin_pct", title="Average Profit Margin Trend",
                       color_discrete_sequence=["#10B981"])
        fig2.update_layout(xaxis_title="Month", yaxis_title="Profit Margin (%)")
        charts["chart_margin_trend"] = style_fig(fig2, 440)

        chart_details["chart_margin_trend"] = (
            "Filled area chart shows net margin percentage evolution over time. "
            "Consistently maintaining positive margin percentages protects enterprise cash flow."
        )
    else:
        charts["chart_margin_trend"] = empty_fig("Map a Date column to see the margin trend")
        chart_details["chart_margin_trend"] = "Map date and profit fields to monitor margin percentage stability."

    if has(df, "supplier"):
        supplier_profit = df.groupby("supplier", as_index=False)["profit"].sum().sort_values("profit", ascending=False)
        fig3 = px.bar(supplier_profit, x="profit", y="supplier", orientation="h", title="Profit by Supplier",
                      color="profit", color_continuous_scale=CONTINUOUS_SCALE_DIVERGING)
        fig3.update_layout(yaxis=dict(categoryorder="total ascending"), yaxis_title="", xaxis_title="Profit ($)")
        charts["chart_supplier_profit"] = style_fig(fig3, 420)

        best_sp = supplier_profit.iloc[0]
        chart_details["chart_supplier_profit"] = (
            f"Supplier '{best_sp['supplier']}' yielded the highest profit ({fmt_currency(best_sp['profit'])}). "
            f"Supplier margin ranking identifies top value-adding partners across your vendor pool."
        )
    else:
        charts["chart_supplier_profit"] = empty_fig("Map a Supplier column to see profit by supplier")
        chart_details["chart_supplier_profit"] = "Map supplier names to examine vendor-level profit contributions."

    if has(df, "warehouse") and "profit_margin_pct" in df.columns:
        wh_profit = df.groupby("warehouse", as_index=False).agg(
            profit=("profit", "sum"), margin=("profit_margin_pct", "mean")
        ).sort_values("margin", ascending=False)
        fig4 = px.bar(wh_profit, x="margin", y="warehouse", orientation="h", title="Average Profit Margin by Warehouse",
                      color="margin", color_continuous_scale=CONTINUOUS_SCALE_DIVERGING)
        fig4.update_layout(yaxis=dict(categoryorder="total ascending"), yaxis_title="", xaxis_title="Avg Margin (%)")
        charts["chart_warehouse_margin"] = style_fig(fig4, 420)

        best_wm = wh_profit.iloc[0]
        chart_details["chart_warehouse_margin"] = (
            f"Warehouse '{best_wm['warehouse']}' generated the top average margin ({best_wm['margin']:.1f}%). "
            f"Comparing warehouse margins uncovers high-efficiency regional fulfillment nodes."
        )
    else:
        charts["chart_warehouse_margin"] = empty_fig("Map a Warehouse column to see margin by warehouse")
        chart_details["chart_warehouse_margin"] = "Map warehouse facilities to evaluate location profitability."

    veh_key = "vehicle" if "vehicle" in df.columns else ("transport_mode" if "transport_mode" in df.columns else None)
    if veh_key:
        vehicle_profit = df.groupby(veh_key, as_index=False)["profit"].sum().sort_values("profit", ascending=False)
        fig5 = px.bar(vehicle_profit, x="profit", y=veh_key, orientation="h", title="Profit by Vehicle",
                      color="profit", color_continuous_scale=CONTINUOUS_SCALE_DIVERGING)
        fig5.update_layout(yaxis=dict(categoryorder="total ascending"), yaxis_title="", xaxis_title="Profit ($)")
        charts["chart_vehicle_profit"] = style_fig(fig5, 420)

        best_vp = vehicle_profit.iloc[0]
        chart_details["chart_vehicle_profit"] = (
            f"'{best_vp[veh_key]}' earned highest profit ({fmt_currency(best_vp['profit'])}). "
            f"Asset profitability metrics aid fleet modernization investment strategies."
        )
    else:
        charts["chart_vehicle_profit"] = empty_fig("Map a Vehicle or Transport Mode column")
        chart_details["chart_vehicle_profit"] = "Map vehicle or mode fields to examine profitability by asset category."

    if has(df, "delivery_status"):
        status_profit = df.groupby("delivery_status", as_index=False)["profit"].sum().sort_values("profit", ascending=False)
        fig6 = px.bar(status_profit, x="profit", y="delivery_status", orientation="h", title="Profit by Delivery Status",
                      color="delivery_status", color_discrete_map=STATUS_COLORS)
        fig6.update_layout(yaxis_title="", xaxis_title="Profit ($)", showlegend=False, yaxis=dict(categoryorder="total ascending"))
        charts["chart_status_profit"] = style_fig(fig6, 420)

        chart_details["chart_status_profit"] = (
            "Compares profitability across delivery status states. "
            "Delayed shipments frequently incur penalty penalties or customer chargebacks that erode margin."
        )
    else:
        charts["chart_status_profit"] = empty_fig("Map a Delivery Status column")
        chart_details["chart_status_profit"] = "Map delivery status to see margin impacts caused by delivery delays."

    display_cols = [c for c in ["shipment_id", "date", "supplier", "route", "vehicle", "transport_mode",
                                 "revenue", "total_cost", "profit", "profit_margin_pct", "delivery_status"]
                    if c in df.columns]
    ranked = df[display_cols].sort_values("profit", ascending=False)
    table_cols = [c.replace("_", " ").title() for c in display_cols]

    ctx.update(kpi_list=kpi_list, chart_data=chart_payload(charts), chart_details=chart_details,
                table_cols=table_cols, table_rows=table_to_rows(ranked))
    return render_template("profitability_analysis.html", **ctx, gate=None, empty=False)


# ---------------------------------------------------------------------------
# Business Insights
# ---------------------------------------------------------------------------
@app.route("/business-insights")
def business_insights():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    ctx = base_context("business_insights", full_df, df)

    if df.empty:
        return render_template("business_insights.html", **ctx, empty=True)

    insights = generate_insights(df)

    charts = {}
    chart_details = {}

    if has(df, "supplier", "total_cost"):
        supplier_cost = df.groupby("supplier", as_index=False)["total_cost"].mean().sort_values("total_cost", ascending=False)
        fig1 = px.bar(supplier_cost, x="total_cost", y="supplier", orientation="h",
                      title="Average Cost per Shipment by Supplier", color="total_cost",
                      color_continuous_scale=CONTINUOUS_SCALE)
        fig1.update_layout(yaxis=dict(categoryorder="total ascending"), yaxis_title="", xaxis_title="Avg Cost ($)")
        charts["chart_insight_supplier"] = style_fig(fig1)

        chart_details["chart_insight_supplier"] = (
            "Supplier cost benchmarking provides evidence for procurement rate negotiations. "
            "High-cost vendors should be evaluated for volume discounts or alternative sourcing."
        )
    else:
        charts["chart_insight_supplier"] = empty_fig("Map a Supplier and cost column for this visual")
        chart_details["chart_insight_supplier"] = "Map supplier fields to unlock supplier efficiency benchmarking."

    if has(df, "warehouse", "profit_margin_pct"):
        wh_margin = df.groupby("warehouse", as_index=False)["profit_margin_pct"].mean().sort_values("profit_margin_pct", ascending=False)
        fig2 = px.bar(wh_margin, x="profit_margin_pct", y="warehouse", orientation="h", title="Average Profit Margin by Warehouse",
                      color="profit_margin_pct", color_continuous_scale=CONTINUOUS_SCALE_DIVERGING)
        fig2.update_layout(yaxis_title="", xaxis_title="Avg Margin (%)", yaxis=dict(categoryorder="total ascending"))
        charts["chart_insight_warehouse"] = style_fig(fig2)

        chart_details["chart_insight_warehouse"] = (
            "Average profit margin across fulfillment hubs highlights top performing logistics centers. "
            "Low margin warehouses warrant operational workflow audits."
        )
    else:
        charts["chart_insight_warehouse"] = empty_fig("Map a Warehouse, Revenue, and cost column for this visual")
        chart_details["chart_insight_warehouse"] = "Map warehouse and margin fields to evaluate facility-level operational yield."

    ctx.update(insights=insights, chart_data=chart_payload(charts), chart_details=chart_details)
    return render_template("business_insights.html", **ctx, empty=False)


# ---------------------------------------------------------------------------
# Data Explorer
# ---------------------------------------------------------------------------
@app.route("/data-explorer")
def data_explorer():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    ctx = base_context("data_explorer", full_df, df)

    if df.empty:
        return render_template("data_explorer.html", **ctx, empty=True)

    text_cols = [c for c in df.columns if df[c].dtype == object]
    numeric_cols = list(df.select_dtypes(include="number").columns)
    sortable_cols = (["date"] if "date" in df.columns else []) + numeric_cols
    sortable_cols = list(dict.fromkeys(sortable_cols)) or list(df.columns)

    search_term = request.args.get("q", "").strip()
    sort_col = request.args.get("sort_col") or (sortable_cols[0] if sortable_cols else None)
    sort_dir = request.args.get("sort_dir", "desc")

    result_df = df.copy()
    if search_term and text_cols:
        mask = False
        term = search_term.lower()
        for c in text_cols:
            mask = mask | result_df[c].astype(str).str.lower().str.contains(term, na=False)
        result_df = result_df[mask]

    if sort_col and sort_col in result_df.columns:
        result_df = result_df.sort_values(sort_col, ascending=(sort_dir == "asc"))

    priority_cols = ["shipment_id", "date", "origin", "destination", "route", "warehouse",
                      "transport_mode", "vehicle", "driver", "distance_km", "total_cost",
                      "revenue", "profit", "delivery_time_hours", "delivery_status"]
    display_cols = [c for c in priority_cols if c in result_df.columns] or list(result_df.columns)

    ctx.update(
        text_cols=text_cols, sortable_cols=sortable_cols, search_term=search_term,
        sort_col=sort_col, sort_dir=sort_dir, result_count=len(result_df),
        table_cols=[c.replace("_", " ").title() for c in display_cols],
        table_rows=table_to_rows(result_df[display_cols].head(500)),
        showing_capped=len(result_df) > 500,
    )
    return render_template("data_explorer.html", **ctx, empty=False)


@app.route("/data-explorer/download")
def data_explorer_download():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    search_term = request.args.get("q", "").strip()
    sort_col = request.args.get("sort_col")
    sort_dir = request.args.get("sort_dir", "desc")

    text_cols = [c for c in df.columns if df[c].dtype == object]
    result_df = df.copy()
    if search_term and text_cols:
        mask = False
        term = search_term.lower()
        for c in text_cols:
            mask = mask | result_df[c].astype(str).str.lower().str.contains(term, na=False)
        result_df = result_df[mask]
    if sort_col and sort_col in result_df.columns:
        result_df = result_df.sort_values(sort_col, ascending=(sort_dir == "asc"))

    csv_bytes = to_csv_bytes(result_df)
    return send_file(io.BytesIO(csv_bytes), mimetype="text/csv", as_attachment=True,
                      download_name="logistics_search_results.csv")


# ---------------------------------------------------------------------------
# Reports / Export
# ---------------------------------------------------------------------------
@app.route("/reports")
def reports():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    ctx = base_context("reports", full_df, df)

    if df.empty:
        return render_template("reports.html", **ctx, empty=True)

    kpis = compute_kpis(df)
    kpi_list = [("Records to Export", f"{len(df):,}")]
    if "Total Logistics Cost" in kpis:
        kpi_list.append(("Total Cost", fmt_currency(kpis["Total Logistics Cost"])))
    if "Total Revenue" in kpis:
        kpi_list.append(("Total Revenue", fmt_currency(kpis["Total Revenue"])))
    if "Total Profit" in kpis:
        kpi_list.append(("Total Profit", fmt_currency(kpis["Total Profit"])))

    can_build_charts = has(df, "route", "total_cost") or has(df, "month", "total_cost") or has(df, "delivery_status")

    ctx.update(kpi_list=kpi_list, can_build_charts=can_build_charts, query_string=request.query_string.decode())
    return render_template("reports.html", **ctx, empty=False)


def _readable_kpis(kpis: dict) -> dict:
    readable = {}
    for label, value in kpis.items():
        if ("Cost" in label or "Revenue" in label or "Profit" in label) and "%" not in label:
            readable[label] = fmt_currency(value) if isinstance(value, (int, float)) else value
        elif "%" in label or "Rate" in label or "Margin" in label:
            readable[label] = f"{value:.2f}%"
        elif "Shipments" in label:
            readable[label] = fmt_number(value)
        else:
            readable[label] = value
    return readable


@app.route("/reports/csv")
def export_csv():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_bytes = to_csv_bytes(df)
    return send_file(io.BytesIO(csv_bytes), mimetype="text/csv", as_attachment=True,
                      download_name=f"logistics_shipments_{timestamp}.csv")


@app.route("/reports/excel")
def export_excel():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    kpis = _readable_kpis(compute_kpis(df))
    excel_bytes = to_excel_bytes(df, kpis)
    return send_file(io.BytesIO(excel_bytes),
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      as_attachment=True, download_name=f"logistics_report_{timestamp}.xlsx")


@app.route("/reports/pdf")
def export_pdf():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    kpis = _readable_kpis(compute_kpis(df))
    insights = generate_insights(df)
    pdf_bytes = to_pdf_bytes(df, kpis, insights)
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True,
                      download_name=f"logistics_report_{timestamp}.pdf")


@app.route("/reports/charts")
def export_charts():
    sid = get_session_id()
    full_df, source, df = load_filtered(sid)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    figs = {}
    if has(df, "route", "total_cost"):
        fig = px.bar(
            df.groupby("route", as_index=False)["total_cost"].sum().sort_values("total_cost", ascending=False).head(10),
            x="total_cost", y="route", orientation="h", title="Top 10 Most Expensive Routes",
            color="total_cost", color_continuous_scale=CONTINUOUS_SCALE,
        )
        figs["top_routes_by_cost"] = style_fig(fig, 420)
    if has(df, "month", "total_cost"):
        fig = px.bar(df.groupby("month", as_index=False)["total_cost"].sum().sort_values("month"),
                     x="month", y="total_cost", title="Monthly Logistics Cost",
                     color_discrete_sequence=[COLOR_SEQ[0]])
        figs["monthly_cost"] = style_fig(fig, 380)
    if has(df, "delivery_status"):
        status_counts = df["delivery_status"].value_counts().reset_index()
        status_counts.columns = ["delivery_status", "count"]
        fig = px.pie(status_counts, names="delivery_status", values="count",
                     title="Delivery Status Distribution", hole=0.55)
        figs["delivery_status"] = style_fig(fig, 380)

    if not figs:
        return redirect(url_for("reports"))

    zip_bytes = figs_to_zip_bytes(figs)
    return send_file(io.BytesIO(zip_bytes), mimetype="application/zip", as_attachment=True,
                      download_name=f"logistics_charts_{timestamp}.zip")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
