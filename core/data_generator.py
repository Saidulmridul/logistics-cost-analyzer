"""
data_generator.py
------------------
Generates realistic, fully-fictional shipment/logistics data for the
Logistics Cost Analyzer. No external APIs or datasets are used.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Reference/master data used to build realistic combinations
# ---------------------------------------------------------------------------
SUPPLIERS = [
    "Orion Freight Co.", "BlueWave Logistics", "Falcon Transit Group",
    "Summit Cargo Partners", "Meridian Shipping Ltd.", "Atlas Haulage",
    "NorthStar Carriers", "Cobalt Route Systems",
]

WAREHOUSES = [
    "Central Warehouse - Dhaka", "North Hub - Rajshahi", "East Depot - Sylhet",
    "South Terminal - Chattogram", "West Storage - Khulna",
]

DESTINATIONS = [
    "Dhaka City Center", "Rajshahi Industrial Zone", "Sylhet Market District",
    "Chattogram Port Area", "Khulna Trade Zone", "Barisal Distribution Point",
    "Rangpur Retail Hub", "Comilla Logistics Park", "Mymensingh Depot",
    "Jessore Commerce Center", "Bogura Supply Point", "Cox's Bazar Terminal",
]

VEHICLE_TYPES = [
    ("Light Van", 0.9, 1.0),
    ("Medium Truck", 1.3, 1.6),
    ("Heavy Truck", 1.8, 2.3),
    ("Refrigerated Truck", 2.1, 2.7),
    ("Trailer", 2.5, 3.2),
]

DRIVERS = [
    "M. Rahman", "S. Ahmed", "K. Islam", "T. Hossain", "R. Chowdhury",
    "A. Karim", "N. Begum", "F. Alam", "J. Miah", "P. Das",
    "H. Siddique", "L. Akter", "Y. Mahmud", "D. Roy", "B. Sarkar",
]

DELIVERY_STATUSES = ["On Time", "Delayed", "Early", "Cancelled"]
DELIVERY_STATUS_WEIGHTS = [0.70, 0.18, 0.09, 0.03]


def _random_dates(n, rng, start_days_ago=365, end_days_ago=0):
    """Return n random dates within the given lookback window."""
    today = datetime.now().date()
    offsets = rng.integers(end_days_ago, start_days_ago, size=n)
    return [today - timedelta(days=int(o)) for o in offsets]


def generate_shipment_data(n=1500, seed=42) -> pd.DataFrame:
    """
    Generate a DataFrame of n fictional shipment records with realistic,
    internally-consistent cost/revenue relationships.
    """
    rng = np.random.default_rng(seed)

    dates = _random_dates(n, rng, start_days_ago=365, end_days_ago=0)

    suppliers = rng.choice(SUPPLIERS, size=n)
    warehouses = rng.choice(WAREHOUSES, size=n)
    destinations = rng.choice(DESTINATIONS, size=n)
    drivers = rng.choice(DRIVERS, size=n)

    vehicle_idx = rng.integers(0, len(VEHICLE_TYPES), size=n)
    vehicle_types = np.array([VEHICLE_TYPES[i][0] for i in vehicle_idx])
    cost_factor_low = np.array([VEHICLE_TYPES[i][1] for i in vehicle_idx])
    cost_factor_high = np.array([VEHICLE_TYPES[i][2] for i in vehicle_idx])
    cost_factor = rng.uniform(cost_factor_low, cost_factor_high)

    # Distance: 20km - 900km, right-skewed (most short/medium haul)
    distance_km = np.round(rng.gamma(shape=2.2, scale=90, size=n) + 15, 1)
    distance_km = np.clip(distance_km, 15, 950)

    # Fuel cost scales with distance & vehicle factor + noise
    fuel_price_per_km = rng.normal(loc=0.85, scale=0.08, size=n)
    fuel_cost = np.round(distance_km * fuel_price_per_km * cost_factor, 2)
    fuel_cost = np.clip(fuel_cost, 10, None)

    # Labor cost: base + per-km rate, influenced by delivery time later
    labor_cost = np.round(
        (distance_km * rng.uniform(0.25, 0.45, size=n) * cost_factor)
        + rng.normal(20, 5, size=n),
        2,
    )
    labor_cost = np.clip(labor_cost, 8, None)

    # Maintenance cost: random spikes to simulate breakdowns/service events
    base_maintenance = rng.gamma(shape=1.5, scale=12, size=n) * cost_factor
    spike_mask = rng.random(n) < 0.08
    base_maintenance[spike_mask] *= rng.uniform(2.5, 4.5, size=spike_mask.sum())
    maintenance_cost = np.round(base_maintenance, 2)

    # Toll cost roughly proportional to distance
    toll_cost = np.round(distance_km * rng.uniform(0.03, 0.09, size=n), 2)

    # Other charges - handling, permits, misc
    other_charges = np.round(rng.uniform(5, 45, size=n), 2)

    total_cost = np.round(
        fuel_cost + labor_cost + maintenance_cost + toll_cost + other_charges, 2
    )

    # Revenue: markup over cost with market variability
    margin_factor = rng.normal(loc=1.28, scale=0.12, size=n)
    margin_factor = np.clip(margin_factor, 0.85, 1.75)
    revenue = np.round(total_cost * margin_factor, 2)

    profit = np.round(revenue - total_cost, 2)

    # Delivery time (hours): scales with distance, plus random delays
    base_hours = distance_km / rng.uniform(38, 55, size=n)  # avg speed km/h
    delay_noise = rng.normal(0, 1.5, size=n)
    delivery_time_hours = np.round(np.clip(base_hours + delay_noise, 1, None), 1)

    delivery_status = rng.choice(
        DELIVERY_STATUSES, size=n, p=DELIVERY_STATUS_WEIGHTS
    )
    # Cancelled shipments -> no revenue/profit, minimal cost recorded
    cancelled_mask = delivery_status == "Cancelled"
    revenue[cancelled_mask] = 0.0
    profit[cancelled_mask] = -total_cost[cancelled_mask] * 0.3
    total_cost[cancelled_mask] = np.round(total_cost[cancelled_mask] * 0.3, 2)

    shipment_ids = [f"SHP-{i+1:06d}" for i in range(n)]
    routes = [f"{w.split(' - ')[-1]} → {d}" for w, d in zip(warehouses, destinations)]

    df = pd.DataFrame({
        "shipment_id": shipment_ids,
        "date": pd.to_datetime(dates),
        "supplier": suppliers,
        "warehouse": warehouses,
        "destination": destinations,
        "route": routes,
        "vehicle_type": vehicle_types,
        "driver": drivers,
        "distance_km": distance_km,
        "fuel_cost": fuel_cost,
        "labor_cost": labor_cost,
        "maintenance_cost": maintenance_cost,
        "toll_cost": toll_cost,
        "other_charges": other_charges,
        "total_cost": total_cost,
        "revenue": revenue,
        "profit": np.round(profit, 2),
        "delivery_time_hours": delivery_time_hours,
        "delivery_status": delivery_status,
    })

    df = df.sort_values("date").reset_index(drop=True)
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["cost_per_km"] = np.round(df["total_cost"] / df["distance_km"], 2)
    df["profit_margin_pct"] = np.round(
        np.where(df["revenue"] > 0, (df["profit"] / df["revenue"]) * 100, 0), 2
    )

    return df


if __name__ == "__main__":
    data = generate_shipment_data(1500)
    print(data.head())
    print(data.shape)
