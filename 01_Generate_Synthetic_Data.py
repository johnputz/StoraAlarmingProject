# Databricks notebook source
# DBTITLE 1,Setup & Configuration
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import uuid
from pyspark.sql import SparkSession
from pyspark.sql.types import *
import pyspark.sql.functions as F

spark = SparkSession.builder.getOrCreate()

# Configuration
CATALOG = "qa_analytics"
SCHEMA = "jyp_schema"
TABLE_PREFIX = "stora_alarm_"
DAYS = 7  # Generate 7 days of data
START_DATE = datetime(2025, 7, 1)  # Starting date for synthetic data
END_DATE = START_DATE + timedelta(days=DAYS)

def table_name(name):
    return f"{CATALOG}.{SCHEMA}.{TABLE_PREFIX}{name}"

print(f"Generating {DAYS} days of synthetic data from {START_DATE.date()} to {END_DATE.date()}")
print(f"Tables will be written to: {CATALOG}.{SCHEMA}.{TABLE_PREFIX}*")

# COMMAND ----------

# DBTITLE 1,Define Resources
# Define our 4 Simpsons-themed resources
resources = [
    {
        "resource_id": "RES-001",
        "resource_name": "Springfield Solar",
        "resource_type": "solar",
        "iso": "CAISO",
        "node": "SPRNGFLD_1_SOLAR",
        "nameplate_mw": 50.0,
        "capacity_mwh": None,  # Solar has no storage
        "client_name": "Springfield Power Co"
    },
    {
        "resource_id": "RES-002",
        "resource_name": "Burns Battery",
        "resource_type": "battery",
        "iso": "CAISO",
        "node": "BURNS_1_BESS",
        "nameplate_mw": 100.0,
        "capacity_mwh": 400.0,  # 4-hour duration
        "client_name": "Burns Industries"
    },
    {
        "resource_id": "RES-003",
        "resource_name": "Shelbyville Sun & Store",
        "resource_type": "hybrid",
        "iso": "CAISO",
        "node": "SHELBY_2_HYBRD",
        "nameplate_mw": 75.0,  # Combined inverter limit
        "capacity_mwh": 200.0,  # 2.67-hour battery
        "client_name": "Shelbyville Municipal"
    },
    {
        "resource_id": "RES-004",
        "resource_name": "Krusty's Clean Energy",
        "resource_type": "hybrid",
        "iso": "CAISO",
        "node": "KRUSTY_1_HYBRD",
        "nameplate_mw": 60.0,
        "capacity_mwh": 150.0,  # 2.5-hour battery
        "client_name": "Krusty Brand Enterprises"
    }
]

resources_df = pd.DataFrame(resources)
print(resources_df[["resource_id", "resource_name", "resource_type", "nameplate_mw", "capacity_mwh"]].to_string(index=False))

# COMMAND ----------

# DBTITLE 1,Generate Price Data (LMPs)
np.random.seed(42)

def generate_lmp_prices(start_date, days, node):
    """Generate realistic CAISO LMP prices with some negative price periods."""
    records = []
    for day_offset in range(days):
        date = start_date + timedelta(days=day_offset)
        is_weekend = date.weekday() >= 5
        
        for he in range(1, 25):  # Hour ending 1-24
            # Base price pattern: low overnight, high afternoon
            if he <= 6:  # Early morning
                base = np.random.normal(25, 10)
            elif he <= 10:  # Morning ramp
                base = np.random.normal(45, 15)
            elif he <= 16:  # Solar hours - can go negative
                base = np.random.normal(15, 25)  # Wide variance, can be negative
            elif he <= 20:  # Evening peak
                base = np.random.normal(80, 30)
            else:  # Late evening
                base = np.random.normal(35, 12)
            
            if is_weekend:
                base *= 0.7
            
            # Inject some very negative price periods (oversupply)
            if day_offset in [2, 5] and 11 <= he <= 15:
                base = np.random.normal(-40, 20)  # Deliberate negative prices
            
            # Inject a price spike
            if day_offset == 4 and he == 19:
                base = np.random.normal(350, 50)  # Price spike
            
            da_lmp = round(base, 2)
            # RT price is DA + noise (more volatile)
            rt_lmp = round(da_lmp + np.random.normal(0, 15), 2)
            
            records.append({
                "node": node,
                "operating_date": date.date(),
                "hour_ending": he,
                "da_lmp": da_lmp,
                "rt_lmp": rt_lmp
            })
    return records

# Generate prices for each node
all_prices = []
for res in resources:
    prices = generate_lmp_prices(START_DATE, DAYS, res["node"])
    all_prices.extend(prices)

prices_df = pd.DataFrame(all_prices)
print(f"Generated {len(prices_df)} price records")
print(f"\nPrice summary:")
print(f"  DA LMP range: ${prices_df['da_lmp'].min():.2f} to ${prices_df['da_lmp'].max():.2f}")
print(f"  Negative price hours: {(prices_df['da_lmp'] < 0).sum()}")
print(f"  Spike hours (>$200): {(prices_df['da_lmp'] > 200).sum()}")

# COMMAND ----------

# DBTITLE 1,Generate Bids
def generate_bids(resources, start_date, days, prices_df):
    """Generate DA and RT bids for each resource."""
    records = []
    bid_counter = 0
    
    for res in resources:
        res_prices = prices_df[prices_df["node"] == res["node"]]
        
        for day_offset in range(days):
            date = start_date + timedelta(days=day_offset)
            
            # DA bids submitted day before
            submit_time = date - timedelta(hours=np.random.randint(10, 14))
            
            # Deliberate anomaly: skip DA bid submission for Burns Battery on day 3
            if res["resource_id"] == "RES-002" and day_offset == 3:
                continue  # Bid not submitted!
            
            for he in range(1, 25):
                bid_counter += 1
                
                if res["resource_type"] == "solar":
                    # Solar bids based on expected generation (0 at night)
                    if 7 <= he <= 19:
                        solar_curve = max(0, np.sin((he - 6) * np.pi / 14))
                        bid_mw = round(res["nameplate_mw"] * solar_curve * np.random.uniform(0.8, 1.0), 1)
                    else:
                        bid_mw = 0.0
                    bid_price = -30.0  # Solar bids at negative to ensure dispatch
                    bid_type = "supply"
                    
                elif res["resource_type"] == "battery":
                    # Batteries: discharge during peak, charge during low/negative prices
                    day_prices = res_prices[
                        (res_prices["operating_date"] == date.date()) & 
                        (res_prices["hour_ending"] == he)
                    ]
                    expected_price = day_prices["da_lmp"].values[0] if len(day_prices) > 0 else 40
                    
                    if he <= 8 or (11 <= he <= 15):  # Charge periods
                        bid_mw = round(res["nameplate_mw"] * np.random.uniform(0.5, 0.8), 1)
                        bid_price = round(expected_price + np.random.uniform(5, 20), 2)
                        bid_type = "demand"
                    else:  # Discharge periods
                        bid_mw = round(res["nameplate_mw"] * np.random.uniform(0.6, 0.95), 1)
                        bid_price = round(max(0, expected_price - np.random.uniform(5, 15)), 2)
                        bid_type = "supply"
                        
                else:  # Hybrid
                    if 7 <= he <= 19:  # Solar generating hours
                        solar_curve = max(0, np.sin((he - 6) * np.pi / 14))
                        solar_mw = res["nameplate_mw"] * 0.6 * solar_curve
                        bid_mw = round(solar_mw * np.random.uniform(0.8, 1.0), 1)
                        bid_price = -25.0
                        bid_type = "supply"
                    elif he >= 17:  # Battery discharge
                        bid_mw = round(res["nameplate_mw"] * 0.4 * np.random.uniform(0.6, 0.9), 1)
                        bid_price = round(np.random.uniform(30, 60), 2)
                        bid_type = "supply"
                    else:  # Early morning charge
                        bid_mw = round(res["nameplate_mw"] * 0.4 * np.random.uniform(0.4, 0.7), 1)
                        bid_price = round(np.random.uniform(20, 40), 2)
                        bid_type = "demand"
                
                if bid_mw > 0:
                    records.append({
                        "bid_id": f"BID-{bid_counter:06d}",
                        "resource_id": res["resource_id"],
                        "market": "DA",
                        "operating_date": date.date(),
                        "hour_ending": he,
                        "bid_mw": bid_mw,
                        "bid_price": bid_price,
                        "bid_type": bid_type,
                        "product": "energy",
                        "submitted_at": submit_time
                    })
    
    return records

bids_records = generate_bids(resources, START_DATE, DAYS, prices_df)
bids_df = pd.DataFrame(bids_records)
print(f"Generated {len(bids_df)} bid records")
print(f"\nBids by resource:")
print(bids_df.groupby("resource_id")["bid_id"].count().to_string())
print(f"\nMissing bid day (Burns Battery day 3): {bids_df[(bids_df['resource_id']=='RES-002') & (bids_df['operating_date']==datetime(2025,7,4).date())].empty}")

# COMMAND ----------

# DBTITLE 1,Generate Awards
def generate_awards(bids_df, prices_df):
    """Generate awards based on bids vs clearing prices."""
    records = []
    
    for _, bid in bids_df.iterrows():
        # Look up the clearing price for this hour/node
        res = next(r for r in resources if r["resource_id"] == bid["resource_id"])
        price_row = prices_df[
            (prices_df["node"] == res["node"]) & 
            (prices_df["operating_date"] == bid["operating_date"]) &
            (prices_df["hour_ending"] == bid["hour_ending"])
        ]
        
        if price_row.empty:
            continue
            
        clearing_price = price_row["da_lmp"].values[0]
        
        # Determine if bid is awarded
        awarded = False
        if bid["bid_type"] == "supply":
            # Supply bid awarded if bid price <= clearing price
            awarded = bid["bid_price"] <= clearing_price
        else:
            # Demand bid awarded if bid price >= clearing price
            awarded = bid["bid_price"] >= clearing_price
        
        if awarded:
            # Sometimes partial award
            if np.random.random() < 0.1:
                awarded_mw = round(bid["bid_mw"] * np.random.uniform(0.5, 0.9), 1)
            else:
                awarded_mw = bid["bid_mw"]
            
            records.append({
                "award_id": f"AWD-{len(records)+1:06d}",
                "resource_id": bid["resource_id"],
                "market": bid["market"],
                "operating_date": bid["operating_date"],
                "hour_ending": bid["hour_ending"],
                "awarded_mw": awarded_mw,
                "clearing_price": round(clearing_price, 2),
                "product": bid["product"]
            })
    
    return records

awards_records = generate_awards(bids_df, prices_df)
awards_df = pd.DataFrame(awards_records)
print(f"Generated {len(awards_df)} award records")
print(f"\nAwards by resource:")
print(awards_df.groupby("resource_id")["award_id"].count().to_string())

# COMMAND ----------

# DBTITLE 1,Generate Dispatch Instructions
def generate_dispatch(awards_df, resources):
    """Generate dispatch instructions based on awards, with some deviations."""
    records = []
    dispatch_counter = 0
    
    for _, award in awards_df.iterrows():
        dispatch_counter += 1
        res = next(r for r in resources if r["resource_id"] == award["resource_id"])
        
        # Dispatch generally follows award
        instructed_mw = award["awarded_mw"]
        
        # Anomaly: dispatch exceeds nameplate for Shelbyville on day 5
        if res["resource_id"] == "RES-003" and award["operating_date"] == (START_DATE + timedelta(days=5)).date() and award["hour_ending"] == 18:
            instructed_mw = res["nameplate_mw"] * 1.15  # 15% over nameplate!
        
        timestamp = datetime.combine(
            award["operating_date"],
            datetime.min.time()
        ) + timedelta(hours=award["hour_ending"] - 1, minutes=np.random.randint(0, 5))
        
        records.append({
            "dispatch_id": f"DSP-{dispatch_counter:06d}",
            "resource_id": award["resource_id"],
            "operating_date": award["operating_date"],
            "timestamp": timestamp,
            "instructed_mw": round(instructed_mw, 1),
            "duration_min": 60
        })
    
    return records

dispatch_records = generate_dispatch(awards_df, resources)
dispatch_df = pd.DataFrame(dispatch_records)
print(f"Generated {len(dispatch_df)} dispatch instruction records")
print(f"\nOver-nameplate dispatch (Shelbyville): {dispatch_df[dispatch_df['instructed_mw'] > 75].shape[0]} records")

# COMMAND ----------

# DBTITLE 1,Generate Meter Reads & SOC
def generate_meter_and_soc(dispatch_df, resources, start_date, days):
    """Generate meter reads that mostly follow dispatch, with some deviations.
    Also generate SOC readings for battery/hybrid resources."""
    meter_records = []
    soc_records = []
    meter_counter = 0
    soc_counter = 0
    
    for res in resources:
        # Initialize SOC for battery-containing resources
        if res["capacity_mwh"] is not None:
            current_soc_mwh = res["capacity_mwh"] * 0.5  # Start at 50%
        
        for day_offset in range(days):
            date = start_date + timedelta(days=day_offset)
            
            for he in range(1, 25):
                meter_counter += 1
                timestamp = datetime.combine(date.date(), datetime.min.time()) + timedelta(hours=he - 1, minutes=30)
                
                # Find dispatch for this hour
                disp = dispatch_df[
                    (dispatch_df["resource_id"] == res["resource_id"]) &
                    (dispatch_df["operating_date"] == date.date()) &
                    (dispatch_df["timestamp"].dt.hour == he - 1)
                ]
                
                if not disp.empty:
                    instructed = disp["instructed_mw"].values[0]
                else:
                    instructed = 0.0
                
                # Meter generally follows dispatch with small noise
                actual_mw = instructed + np.random.normal(0, abs(instructed) * 0.02 + 0.1)
                
                # ANOMALY: Burns Battery not following dispatch on day 6, hours 17-20
                # (generating when it should be idle or dispatched differently)
                if res["resource_id"] == "RES-002" and day_offset == 6 and 17 <= he <= 20:
                    actual_mw = instructed + np.random.uniform(15, 30)  # Way over dispatch
                
                # ANOMALY: Krusty's generating during very negative prices on day 2 with low SOC
                if res["resource_id"] == "RES-004" and day_offset == 2 and 12 <= he <= 14:
                    actual_mw = 25.0  # Generating when prices are -$40 and SOC is low
                
                # Clamp solar to 0 at night
                if res["resource_type"] == "solar" and (he < 7 or he > 19):
                    actual_mw = max(0, actual_mw)
                
                actual_mw = round(actual_mw, 2)
                
                meter_records.append({
                    "meter_id": f"MTR-{meter_counter:06d}",
                    "resource_id": res["resource_id"],
                    "timestamp": timestamp,
                    "actual_mw": actual_mw,
                    "interval_seconds": 3600
                })
                
                # Update SOC for battery/hybrid
                if res["capacity_mwh"] is not None:
                    soc_counter += 1
                    # Positive actual_mw = discharging (SOC decreases)
                    # Negative actual_mw = charging (SOC increases)
                    energy_change = -actual_mw * 1.0  # 1 hour interval
                    current_soc_mwh = np.clip(
                        current_soc_mwh + energy_change,
                        0, res["capacity_mwh"]
                    )
                    
                    # ANOMALY: Force Krusty's SOC very low on day 2 (for the negative price rule)
                    if res["resource_id"] == "RES-004" and day_offset == 2 and he == 11:
                        current_soc_mwh = res["capacity_mwh"] * 0.08  # 8% SOC
                    
                    # ANOMALY: Burns Battery SOC flatline on day 1 (meter/BMS issue)
                    if res["resource_id"] == "RES-002" and day_offset == 1 and 8 <= he <= 16:
                        frozen_soc = res["capacity_mwh"] * 0.45
                        current_soc_mwh = frozen_soc  # SOC not changing despite activity
                    
                    soc_pct = round((current_soc_mwh / res["capacity_mwh"]) * 100, 1)
                    
                    soc_records.append({
                        "soc_id": f"SOC-{soc_counter:06d}",
                        "resource_id": res["resource_id"],
                        "timestamp": timestamp,
                        "soc_pct": soc_pct,
                        "soc_mwh": round(current_soc_mwh, 2)
                    })
    
    return meter_records, soc_records

meter_records, soc_records = generate_meter_and_soc(dispatch_df, resources, START_DATE, DAYS)
meter_df = pd.DataFrame(meter_records)
soc_df = pd.DataFrame(soc_records)

print(f"Generated {len(meter_df)} meter records")
print(f"Generated {len(soc_df)} SOC records")
print(f"\nSOC range by resource:")
for res_id in ["RES-002", "RES-003", "RES-004"]:
    res_soc = soc_df[soc_df["resource_id"] == res_id]
    print(f"  {res_id}: {res_soc['soc_pct'].min():.1f}% - {res_soc['soc_pct'].max():.1f}%")

# COMMAND ----------

# DBTITLE 1,Generate Rules Configuration
# Starter rules matching our scope document
rules_data = [
    {
        "rule_id": "E1",
        "rule_name": "Generating at negative prices (low SOC)",
        "severity": "RED",
        "condition_expression": "actual_mw > 5 AND da_lmp < -20 AND soc_pct < 10",
        "recommended_action": "Investigate immediately — resource should not be discharging at negative prices with minimal stored energy. Check Stora bid logic and dispatch compliance.",
        "applies_to_types": "battery,hybrid",
        "is_active": True,
        "created_at": datetime(2025, 6, 15),
        "updated_at": datetime(2025, 6, 15),
        "created_by": "system"
    },
    {
        "rule_id": "E2",
        "rule_name": "Generating at negative prices (high SOC)",
        "severity": "YELLOW",
        "condition_expression": "actual_mw > 5 AND da_lmp < -50 AND soc_pct > 50",
        "recommended_action": "Review — may be intentional (AS obligation or ramp constraint) but warrants verification.",
        "applies_to_types": "battery,hybrid",
        "is_active": True,
        "created_at": datetime(2025, 6, 15),
        "updated_at": datetime(2025, 6, 15),
        "created_by": "system"
    },
    {
        "rule_id": "E3",
        "rule_name": "Charging at high positive prices",
        "severity": "YELLOW",
        "condition_expression": "actual_mw < -5 AND da_lmp > 200",
        "recommended_action": "Verify whether charge is from an AS award or a bidding error.",
        "applies_to_types": "battery,hybrid",
        "is_active": True,
        "created_at": datetime(2025, 6, 15),
        "updated_at": datetime(2025, 6, 15),
        "created_by": "system"
    },
    {
        "rule_id": "E4",
        "rule_name": "Bid not submitted",
        "severity": "RED",
        "condition_expression": "no_bid_for_operating_day = True",
        "recommended_action": "Stora may have failed to submit. Check Stora logs and resubmit manually if needed.",
        "applies_to_types": "battery,solar,hybrid",
        "is_active": True,
        "created_at": datetime(2025, 6, 15),
        "updated_at": datetime(2025, 6, 15),
        "created_by": "system"
    },
    {
        "rule_id": "D1",
        "rule_name": "Dispatch not followed",
        "severity": "RED",
        "condition_expression": "abs(actual_mw - instructed_mw) > max(5, instructed_mw * 0.10)",
        "recommended_action": "Resource is non-compliant. Check plant status, communications, and inverter faults.",
        "applies_to_types": "battery,solar,hybrid",
        "is_active": True,
        "created_at": datetime(2025, 6, 15),
        "updated_at": datetime(2025, 6, 15),
        "created_by": "system"
    },
    {
        "rule_id": "D2",
        "rule_name": "Dispatch exceeds capacity",
        "severity": "YELLOW",
        "condition_expression": "instructed_mw > nameplate_mw",
        "recommended_action": "ISO may have stale parameters. File ticket to update resource limits.",
        "applies_to_types": "battery,solar,hybrid",
        "is_active": True,
        "created_at": datetime(2025, 6, 15),
        "updated_at": datetime(2025, 6, 15),
        "created_by": "system"
    },
    {
        "rule_id": "S1",
        "rule_name": "SOC out of expected bounds",
        "severity": "YELLOW",
        "condition_expression": "soc_pct < 5 OR soc_pct > 95",
        "recommended_action": "May indicate metering drift or unexpected cycling.",
        "applies_to_types": "battery,hybrid",
        "is_active": True,
        "created_at": datetime(2025, 6, 15),
        "updated_at": datetime(2025, 6, 15),
        "created_by": "system"
    },
    {
        "rule_id": "S2",
        "rule_name": "SOC flatline",
        "severity": "YELLOW",
        "condition_expression": "soc_unchanged_hours >= 4 AND has_active_awards = True",
        "recommended_action": "Possible meter/BMS communication failure.",
        "applies_to_types": "battery,hybrid",
        "is_active": True,
        "created_at": datetime(2025, 6, 15),
        "updated_at": datetime(2025, 6, 15),
        "created_by": "system"
    },
    {
        "rule_id": "S3",
        "rule_name": "Throughput exceeds daily limit",
        "severity": "YELLOW",
        "condition_expression": "daily_throughput_mwh > capacity_mwh * 2",
        "recommended_action": "Alert asset manager — may need to curtail to protect warranty.",
        "applies_to_types": "battery,hybrid",
        "is_active": True,
        "created_at": datetime(2025, 6, 15),
        "updated_at": datetime(2025, 6, 15),
        "created_by": "system"
    },
]

rules_df = pd.DataFrame(rules_data)
print(f"Defined {len(rules_df)} rules:")
print(rules_df[["rule_id", "rule_name", "severity"]].to_string(index=False))

# COMMAND ----------

# DBTITLE 1,Initialize Alert, Suppression, and Notification Config Tables
# Empty alerts table (will be populated by rules engine)
alerts_df = pd.DataFrame(columns=[
    "alert_id", "rule_id", "resource_id", "triggered_at", "operating_date",
    "hour_ending", "severity", "message", "details_json",
    "status", "acknowledged_by", "acknowledged_at",
    "resolved_by", "resolved_at", "resolution_notes"
])

# Empty suppressions table
suppressions_df = pd.DataFrame(columns=[
    "suppression_id", "rule_id", "resource_id",
    "created_by", "created_at", "expires_at", "reason"
])

# Default notification config
notification_config_data = [
    {
        "config_id": "NOTIF-001",
        "resource_id": None,  # All resources
        "severity_threshold": "RED",
        "email_list": "ops-team@springfieldpower.com,alerts@burnsindustries.com",
        "is_active": True
    },
    {
        "config_id": "NOTIF-002",
        "resource_id": "RES-002",  # Burns Battery specifically
        "severity_threshold": "YELLOW",
        "email_list": "smithers@burnsindustries.com",
        "is_active": True
    }
]
notification_config_df = pd.DataFrame(notification_config_data)

print("Initialized empty alerts and suppressions tables")
print(f"Notification configs: {len(notification_config_df)} entries")
print(notification_config_df.to_string(index=False))

# COMMAND ----------

# DBTITLE 1,Write All Tables to Delta
# Convert pandas DataFrames to Spark and write as Delta tables

def write_table(pdf, name, mode="overwrite"):
    """Write a pandas DataFrame as a Delta table."""
    full_name = table_name(name)
    sdf = spark.createDataFrame(pdf)
    sdf.write.format("delta").mode(mode).saveAsTable(full_name)
    count = spark.table(full_name).count()
    print(f"  ✓ {full_name}: {count} rows")

print("Writing tables to Delta...\n")

# Resources
write_table(resources_df, "resources")

# Prices
write_table(prices_df, "prices")

# Bids
bids_df["submitted_at"] = pd.to_datetime(bids_df["submitted_at"])
write_table(bids_df, "bids")

# Awards
write_table(awards_df, "awards")

# Dispatch
dispatch_df["timestamp"] = pd.to_datetime(dispatch_df["timestamp"])
write_table(dispatch_df, "dispatch_instructions")

# Meter reads
meter_df["timestamp"] = pd.to_datetime(meter_df["timestamp"])
write_table(meter_df, "meter_reads")

# SOC readings
soc_df["timestamp"] = pd.to_datetime(soc_df["timestamp"])
write_table(soc_df, "soc_readings")

# Rules
rules_df["created_at"] = pd.to_datetime(rules_df["created_at"])
rules_df["updated_at"] = pd.to_datetime(rules_df["updated_at"])
write_table(rules_df, "rules")

# Alerts (empty schema)
if alerts_df.empty:
    schema = StructType([
        StructField("alert_id", StringType()),
        StructField("rule_id", StringType()),
        StructField("resource_id", StringType()),
        StructField("triggered_at", TimestampType()),
        StructField("operating_date", DateType()),
        StructField("hour_ending", IntegerType()),
        StructField("severity", StringType()),
        StructField("message", StringType()),
        StructField("details_json", StringType()),
        StructField("status", StringType()),
        StructField("acknowledged_by", StringType()),
        StructField("acknowledged_at", TimestampType()),
        StructField("resolved_by", StringType()),
        StructField("resolved_at", TimestampType()),
        StructField("resolution_notes", StringType()),
    ])
    spark.createDataFrame([], schema).write.format("delta").mode("overwrite").saveAsTable(table_name("alerts"))
    print(f"  ✓ {table_name('alerts')}: 0 rows (schema initialized)")

# Suppressions (empty schema)
supp_schema = StructType([
    StructField("suppression_id", StringType()),
    StructField("rule_id", StringType()),
    StructField("resource_id", StringType()),
    StructField("created_by", StringType()),
    StructField("created_at", TimestampType()),
    StructField("expires_at", TimestampType()),
    StructField("reason", StringType()),
])
spark.createDataFrame([], supp_schema).write.format("delta").mode("overwrite").saveAsTable(table_name("suppressions"))
print(f"  ✓ {table_name('suppressions')}: 0 rows (schema initialized)")

# Notification config
write_table(notification_config_df, "notification_config")

print("\n✅ All tables written successfully!")

# COMMAND ----------

# DBTITLE 1,Verify: Summary of Planted Anomalies
print("""
╔══════════════════════════════════════════════════════════════════════════╗
║                    PLANTED ANOMALIES SUMMARY                            ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  1. Burns Battery (RES-002) - Day 4 (Jul 4):                            ║
║     → DA bid NOT SUBMITTED (triggers rule E4)                            ║
║                                                                          ║
║  2. Burns Battery (RES-002) - Day 2 (Jul 2):                            ║
║     → SOC flatline hours 8-16 despite active awards (triggers S2)        ║
║                                                                          ║
║  3. Burns Battery (RES-002) - Day 7 (Jul 7), HE 17-20:                  ║
║     → Meter reads 15-30 MW over dispatch (triggers D1)                   ║
║                                                                          ║
║  4. Krusty's Clean Energy (RES-004) - Day 3 (Jul 3), HE 12-14:          ║
║     → Generating 25 MW at LMP ~ -$40 with SOC ~8% (triggers E1)         ║
║                                                                          ║
║  5. Shelbyville Sun & Store (RES-003) - Day 6 (Jul 6), HE 18:           ║
║     → Dispatch instruction 86.25 MW > nameplate 75 MW (triggers D2)      ║
║                                                                          ║
║  6. Price spikes/negatives (Days 3 & 6) may trigger E2/E3               ║
║     depending on resource behavior during those hours                     ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
""")