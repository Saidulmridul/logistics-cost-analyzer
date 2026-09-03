"""
schema.py
----------
Defines the application's standard field taxonomy. Every uploaded dataset,
regardless of its original column names, is mapped onto this taxonomy so the
rest of the app (KPIs, charts, filters, insights, exports) can work with one
consistent set of field names.
"""

from dataclasses import dataclass, field


@dataclass
class FieldDef:
    key: str            # standardized internal name
    label: str           # human friendly label shown in the UI
    group: str           # "dimension", "measure", "cost", "financial", "status"
    dtype: str           # "date", "numeric", "text"
    required: bool = False
    derivable: bool = False   # can be computed from other fields if missing
    synonyms: tuple = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# The full standard schema
# ---------------------------------------------------------------------------
FIELDS = [
    FieldDef("shipment_id", "Shipment ID", "dimension", "text", synonyms=(
        "shipment id", "shipment", "shipment no", "order id", "order number",
        "tracking id", "tracking number", "id",
    )),
    FieldDef("date", "Date", "dimension", "date", required=True, synonyms=(
        "date", "shipment date", "order date", "delivery date", "ship date",
    )),
    FieldDef("origin", "Origin", "dimension", "text", synonyms=(
        "origin", "origin city", "source", "source city", "pickup location",
        "warehouse origin", "from",
    )),
    FieldDef("destination", "Destination", "dimension", "text", synonyms=(
        "destination", "destination city", "delivery location", "to", "drop location",
    )),
    FieldDef("route", "Route", "dimension", "text", derivable=True, synonyms=(
        "route", "shipping route", "lane",
    )),
    FieldDef("vehicle", "Vehicle", "dimension", "text", synonyms=(
        "vehicle", "vehicle id", "vehicle no", "truck id", "truck number",
    )),
    FieldDef("transport_mode", "Transport Mode", "dimension", "text", synonyms=(
        "transport mode", "transport type", "mode", "shipping mode", "vehicle type",
        "carrier type",
    )),
    FieldDef("warehouse", "Warehouse", "dimension", "text", synonyms=(
        "warehouse", "warehouse name", "depot", "distribution center", "dc",
    )),
    FieldDef("customer", "Customer", "dimension", "text", synonyms=(
        "customer", "client", "customer name", "consignee",
    )),
    FieldDef("supplier", "Supplier / Carrier", "dimension", "text", synonyms=(
        "supplier", "carrier", "vendor", "logistics provider", "3pl",
    )),
    FieldDef("driver", "Driver", "dimension", "text", synonyms=(
        "driver", "driver name", "driver id",
    )),
    FieldDef("product_category", "Product Category", "dimension", "text", synonyms=(
        "product category", "category", "product type", "commodity",
    )),

    # Measures
    FieldDef("distance_km", "Distance (km)", "measure", "numeric", synonyms=(
        "distance", "distance km", "distance (km)", "total distance", "km",
    )),
    FieldDef("weight", "Weight", "measure", "numeric", synonyms=(
        "weight", "shipment weight", "cargo weight", "total weight", "weight (kg)",
    )),
    FieldDef("delivery_time_hours", "Delivery Time (hrs)", "measure", "numeric", synonyms=(
        "delivery time", "delivery time (hrs)", "transit time", "delivery duration",
        "actual delivery time",
    )),
    FieldDef("planned_delivery_time_hours", "Planned Delivery Time (hrs)", "measure", "numeric", synonyms=(
        "planned delivery time", "expected delivery time", "promised delivery time",
        "eta hours",
    )),

    # Cost components
    FieldDef("transportation_cost", "Transportation Cost", "cost", "numeric", synonyms=(
        "transportation cost", "transport cost", "travel cost", "freight cost", "shipping cost",
    )),
    FieldDef("fuel_cost", "Fuel Cost", "cost", "numeric", synonyms=(
        "fuel cost", "fuel expense", "fuel charge",
    )),
    FieldDef("warehouse_cost", "Warehouse Cost", "cost", "numeric", synonyms=(
        "warehouse cost", "warehouse expense", "storage cost",
    )),
    FieldDef("labor_cost", "Labor Cost", "cost", "numeric", synonyms=(
        "labor cost", "labour cost", "labor expense", "handling cost",
    )),
    FieldDef("customs_cost", "Customs Cost", "cost", "numeric", synonyms=(
        "customs cost", "customs duty", "customs expense", "duty cost",
    )),
    FieldDef("insurance_cost", "Insurance Cost", "cost", "numeric", synonyms=(
        "insurance cost", "insurance expense", "insurance premium",
    )),
    FieldDef("maintenance_cost", "Maintenance Cost", "cost", "numeric", synonyms=(
        "maintenance cost", "maintenance expense", "repair cost",
    )),
    FieldDef("toll_cost", "Toll Cost", "cost", "numeric", synonyms=(
        "toll cost", "toll expense", "toll charge",
    )),
    FieldDef("other_cost", "Other Charges", "cost", "numeric", synonyms=(
        "other charges", "other cost", "misc cost", "miscellaneous cost", "other expense",
    )),

    # Financials
    FieldDef("total_cost", "Total Logistics Cost", "financial", "numeric", derivable=True, synonyms=(
        "total cost", "total logistics cost", "total expense", "total spend",
    )),
    FieldDef("revenue", "Revenue", "financial", "numeric", synonyms=(
        "revenue", "sales", "total revenue", "billed amount",
    )),
    FieldDef("profit", "Profit", "financial", "numeric", derivable=True, synonyms=(
        "profit", "net profit", "margin amount",
    )),

    # Status
    FieldDef("delivery_status", "Delivery Status", "status", "text", synonyms=(
        "delivery status", "status", "shipment status",
    )),
]

FIELD_MAP = {f.key: f for f in FIELDS}

COST_FIELD_KEYS = [f.key for f in FIELDS if f.group == "cost"]

DIMENSION_KEYS_FOR_FILTERS = [
    "date", "origin", "destination", "route", "vehicle", "transport_mode",
    "warehouse", "customer", "supplier", "driver", "product_category",
    "delivery_status",
]


def normalize_header(name: str) -> str:
    """Lowercase, strip, collapse separators for fuzzy matching."""
    return (
        str(name).strip().lower()
        .replace("_", " ").replace("-", " ")
        .replace("  ", " ")
    )


def suggest_mapping(columns) -> dict:
    """
    Given the raw column names of an uploaded file, return a best-guess
    mapping {standard_key: original_column_name or None}.
    """
    normalized = {normalize_header(c): c for c in columns}
    mapping = {}
    for f in FIELDS:
        match = None
        # exact synonym match first
        for syn in (f.key.replace("_", " "),) + f.synonyms:
            if syn in normalized:
                match = normalized[syn]
                break
        if match is None:
            # loose contains-match as a fallback
            for norm, orig in normalized.items():
                if any(syn in norm or norm in syn for syn in f.synonyms):
                    match = orig
                    break
        mapping[f.key] = match
    return mapping
