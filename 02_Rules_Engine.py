# Databricks notebook source
# DBTITLE 1,Rules Engine - Setup
"""Stora Alarm Rules Engine
Evaluates rules against current data and generates alerts.
Run this after 01_Generate_Synthetic_Data to populate the alerts table.
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import uuid
import json
from pyspark.sql import SparkSession
import pyspark.sql.functions as F

spark = SparkSession.builder.getOrCreate()

CATALOG = "qa_analytics"
SCHEMA = "jyp_schema"
TABLE_PREFIX = "stora_alarm_"

def table_name(name):
    return f"{CATALOG}.{SCHEMA}.{TABLE_PREFIX}{name}"

# Load all tables
resources = spark.table(table_name("resources")).toPandas()
prices = spark.table(table_name("prices")).toPandas()
bids = spark.table(table_name("bids")).toPandas()
awards = spark.table(table_name("awards")).toPandas()
dispatch = spark.table(table_name("dispatch_instructions")).toPandas()
meter = spark.table(table_name("meter_reads")).toPandas()
soc = spark.table(table_name("soc_readings")).toPandas()
rules = spark.table(table_name("rules")).toPandas()
suppressions = spark.table(table_name("suppressions")).toPandas()

print(f"Loaded data: {len(resources)} resources, {len(meter)} meter reads, {len(soc)} SOC records")
print(f"Active rules: {rules['is_active'].sum()} of {len(rules)}")

# COMMAND ----------

# DBTITLE 1,Rule Evaluation Functions
def is_suppressed(rule_id, resource_id, suppressions_df, eval_time):
    """Check if a rule/resource combo is currently suppressed."""
    active = suppressions_df[
        (suppressions_df["rule_id"] == rule_id) &
        (suppressions_df["resource_id"] == resource_id)
    ]
    if active.empty:
        return False
    # Check if any suppression is still valid (not expired)
    for _, supp in active.iterrows():
        if pd.isna(supp["expires_at"]) or supp["expires_at"] > eval_time:
            return True
    return False

def create_alert(rule_id, resource_id, severity, message, details, operating_date, hour_ending, triggered_at):
    """Create an alert record."""
    return {
        "alert_id": str(uuid.uuid4()),
        "rule_id": rule_id,
        "resource_id": resource_id,
        "triggered_at": triggered_at,
        "operating_date": operating_date,
        "hour_ending": int(hour_ending) if hour_ending is not None else None,
        "severity": severity,
        "message": message,
        "details_json": json.dumps(details),
        "status": "OPEN",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_by": None,
        "resolved_at": None,
        "resolution_notes": None
    }

print("Rule evaluation functions defined.")

# COMMAND ----------

# DBTITLE 1,Evaluate All Rules
eval_time = datetime.now()
alerts = []

# Merge meter + SOC + prices + dispatch for evaluation
meter["timestamp"] = pd.to_datetime(meter["timestamp"])
meter["operating_date"] = meter["timestamp"].dt.date
meter["hour_ending"] = meter["timestamp"].dt.hour + 1  # Convert to HE

if not soc.empty:
    soc["timestamp"] = pd.to_datetime(soc["timestamp"])

# Build evaluation dataframe: merge meter with prices, dispatch, SOC, resources
eval_df = meter.merge(
    resources[["resource_id", "resource_type", "nameplate_mw", "capacity_mwh", "node"]],
    on="resource_id"
)

# Merge prices
prices["operating_date"] = pd.to_datetime(prices["operating_date"]).dt.date
eval_df = eval_df.merge(
    prices[["node", "operating_date", "hour_ending", "da_lmp", "rt_lmp"]],
    on=["node", "operating_date", "hour_ending"],
    how="left"
)

# Merge dispatch
dispatch["timestamp"] = pd.to_datetime(dispatch["timestamp"])
dispatch["hour_ending"] = dispatch["timestamp"].dt.hour + 1
eval_df = eval_df.merge(
    dispatch[["resource_id", "operating_date", "hour_ending", "instructed_mw"]],
    on=["resource_id", "operating_date", "hour_ending"],
    how="left"
)

# Merge SOC
if not soc.empty:
    soc["operating_date"] = soc["timestamp"].dt.date
    soc["hour_ending"] = soc["timestamp"].dt.hour + 1
    eval_df = eval_df.merge(
        soc[["resource_id", "operating_date", "hour_ending", "soc_pct", "soc_mwh"]],
        on=["resource_id", "operating_date", "hour_ending"],
        how="left"
    )

print(f"Evaluation dataframe: {len(eval_df)} rows x {len(eval_df.columns)} columns")
print(f"Columns: {list(eval_df.columns)}")

# COMMAND ----------

# DBTITLE 1,Rule E1: Generating at negative prices (low SOC)
# E1: Resource is generating AND LMP < -$20 AND SOC < 10%
rule = rules[rules["rule_id"] == "E1"].iloc[0]
applicable_types = rule["applies_to_types"].split(",")

violations = eval_df[
    (eval_df["resource_type"].isin(applicable_types)) &
    (eval_df["actual_mw"] > 5) &
    (eval_df["da_lmp"] < -20) &
    (eval_df["soc_pct"] < 10)
]

for _, v in violations.iterrows():
    if not is_suppressed("E1", v["resource_id"], suppressions, eval_time):
        res_name = resources[resources["resource_id"] == v["resource_id"]]["resource_name"].values[0]
        alerts.append(create_alert(
            rule_id="E1",
            resource_id=v["resource_id"],
            severity="RED",
            message=f"{res_name}: Generating {v['actual_mw']:.1f} MW at LMP ${v['da_lmp']:.2f} with SOC at {v['soc_pct']:.1f}%",
            details={"actual_mw": v["actual_mw"], "da_lmp": v["da_lmp"], "soc_pct": v["soc_pct"]},
            operating_date=v["operating_date"],
            hour_ending=v["hour_ending"],
            triggered_at=eval_time
        ))

print(f"Rule E1 (Generating at negative prices, low SOC): {len(violations)} violations → {sum(1 for a in alerts if a['rule_id']=='E1')} alerts")

# COMMAND ----------

# DBTITLE 1,Rule E4: Bid not submitted
# E4: No DA bid for a resource on an operating day
rule = rules[rules["rule_id"] == "E4"].iloc[0]

bids["operating_date"] = pd.to_datetime(bids["operating_date"]).dt.date
all_dates = pd.date_range(START_DATE, END_DATE - timedelta(days=1)).date
START_DATE = datetime(2025, 7, 1)
END_DATE = START_DATE + timedelta(days=7)
all_dates = pd.date_range(START_DATE, END_DATE - timedelta(days=1)).date

for res in resources.itertuples():
    for op_date in all_dates:
        da_bids = bids[
            (bids["resource_id"] == res.resource_id) &
            (bids["market"] == "DA") &
            (bids["operating_date"] == op_date)
        ]
        if da_bids.empty:
            if not is_suppressed("E4", res.resource_id, suppressions, eval_time):
                alerts.append(create_alert(
                    rule_id="E4",
                    resource_id=res.resource_id,
                    severity="RED",
                    message=f"{res.resource_name}: No DA bid submitted for {op_date}",
                    details={"operating_date": str(op_date)},
                    operating_date=op_date,
                    hour_ending=None,
                    triggered_at=eval_time
                ))

print(f"Rule E4 (Bid not submitted): {sum(1 for a in alerts if a['rule_id']=='E4')} alerts")

# COMMAND ----------

# DBTITLE 1,Rule D1: Dispatch not followed
# D1: abs(Meter MW - Dispatch MW) > max(5, instructed_mw * 0.10)
rule = rules[rules["rule_id"] == "D1"].iloc[0]

dispatched = eval_df[eval_df["instructed_mw"].notna() & (eval_df["instructed_mw"].abs() > 1)]
violations_d1 = dispatched[
    (dispatched["actual_mw"] - dispatched["instructed_mw"]).abs() > 
    np.maximum(5, dispatched["instructed_mw"].abs() * 0.10)
]

for _, v in violations_d1.iterrows():
    if not is_suppressed("D1", v["resource_id"], suppressions, eval_time):
        res_name = resources[resources["resource_id"] == v["resource_id"]]["resource_name"].values[0]
        deviation = v["actual_mw"] - v["instructed_mw"]
        alerts.append(create_alert(
            rule_id="D1",
            resource_id=v["resource_id"],
            severity="RED",
            message=f"{res_name}: Meter ({v['actual_mw']:.1f} MW) deviates from dispatch ({v['instructed_mw']:.1f} MW) by {deviation:+.1f} MW",
            details={"actual_mw": v["actual_mw"], "instructed_mw": v["instructed_mw"], "deviation_mw": round(deviation, 1)},
            operating_date=v["operating_date"],
            hour_ending=v["hour_ending"],
            triggered_at=eval_time
        ))

print(f"Rule D1 (Dispatch not followed): {len(violations_d1)} violations → {sum(1 for a in alerts if a['rule_id']=='D1')} alerts")

# COMMAND ----------

# DBTITLE 1,Rule D2: Dispatch exceeds capacity
# D2: Dispatch instruction MW > nameplate
rule = rules[rules["rule_id"] == "D2"].iloc[0]

violations_d2 = eval_df[
    (eval_df["instructed_mw"].notna()) &
    (eval_df["instructed_mw"] > eval_df["nameplate_mw"])
]

for _, v in violations_d2.iterrows():
    if not is_suppressed("D2", v["resource_id"], suppressions, eval_time):
        res_name = resources[resources["resource_id"] == v["resource_id"]]["resource_name"].values[0]
        alerts.append(create_alert(
            rule_id="D2",
            resource_id=v["resource_id"],
            severity="YELLOW",
            message=f"{res_name}: Dispatch {v['instructed_mw']:.1f} MW exceeds nameplate {v['nameplate_mw']:.1f} MW",
            details={"instructed_mw": v["instructed_mw"], "nameplate_mw": v["nameplate_mw"]},
            operating_date=v["operating_date"],
            hour_ending=v["hour_ending"],
            triggered_at=eval_time
        ))

print(f"Rule D2 (Dispatch exceeds capacity): {len(violations_d2)} violations → {sum(1 for a in alerts if a['rule_id']=='D2')} alerts")

# COMMAND ----------

# DBTITLE 1,Rule S2: SOC flatline
# S2: SOC unchanged for >= 4 consecutive hours despite active awards
rule = rules[rules["rule_id"] == "S2"].iloc[0]
applicable_types = rule["applies_to_types"].split(",")

battery_resources = resources[resources["resource_type"].isin(applicable_types)]

for _, res in battery_resources.iterrows():
    res_soc = soc[soc["resource_id"] == res["resource_id"]].sort_values("timestamp").copy()
    if res_soc.empty:
        continue
    
    # Look for stretches where SOC doesn't change
    res_soc["soc_change"] = res_soc["soc_pct"].diff().abs()
    res_soc["is_flat"] = res_soc["soc_change"] < 0.1  # Less than 0.1% change
    
    # Find consecutive flat periods
    consecutive_flat = 0
    flat_start = None
    
    for idx, row in res_soc.iterrows():
        if row["is_flat"]:
            consecutive_flat += 1
            if flat_start is None:
                flat_start = row["timestamp"]
        else:
            if consecutive_flat >= 4:
                # Check if there were awards during this period
                flat_end = row["timestamp"]
                flat_date = flat_start.date() if hasattr(flat_start, 'date') else flat_start
                period_awards = awards[
                    (awards["resource_id"] == res["resource_id"]) &
                    (awards["operating_date"] == flat_date)
                ]
                if not period_awards.empty:
                    if not is_suppressed("S2", res["resource_id"], suppressions, eval_time):
                        alerts.append(create_alert(
                            rule_id="S2",
                            resource_id=res["resource_id"],
                            severity="YELLOW",
                            message=f"{res['resource_name']}: SOC flat at {row['soc_pct']:.1f}% for {consecutive_flat}+ hours despite active awards",
                            details={"flat_hours": consecutive_flat, "soc_pct": row["soc_pct"]},
                            operating_date=flat_date,
                            hour_ending=int(flat_start.hour + 1) if hasattr(flat_start, 'hour') else None,
                            triggered_at=eval_time
                        ))
            consecutive_flat = 0
            flat_start = None

print(f"Rule S2 (SOC flatline): {sum(1 for a in alerts if a['rule_id']=='S2')} alerts")

# COMMAND ----------

# DBTITLE 1,Write Alerts to Delta Table
# Summary
print(f"\n{'='*60}")
print(f"RULES ENGINE COMPLETE")
print(f"{'='*60}")
print(f"Total alerts generated: {len(alerts)}")
print(f"\nBy severity:")
from collections import Counter
severity_counts = Counter(a["severity"] for a in alerts)
for sev, count in sorted(severity_counts.items()):
    print(f"  {sev}: {count}")

print(f"\nBy rule:")
rule_counts = Counter(a["rule_id"] for a in alerts)
for rule_id, count in sorted(rule_counts.items()):
    rule_name = rules[rules["rule_id"] == rule_id]["rule_name"].values[0]
    print(f"  {rule_id} ({rule_name}): {count}")

print(f"\nBy resource:")
res_counts = Counter(a["resource_id"] for a in alerts)
for res_id, count in sorted(res_counts.items()):
    res_name = resources[resources["resource_id"] == res_id]["resource_name"].values[0]
    print(f"  {res_name}: {count}")

# Write to Delta
if alerts:
    alerts_pdf = pd.DataFrame(alerts)
    alerts_pdf["triggered_at"] = pd.to_datetime(alerts_pdf["triggered_at"])
    alerts_pdf["operating_date"] = pd.to_datetime(alerts_pdf["operating_date"])
    
    alerts_sdf = spark.createDataFrame(alerts_pdf)
    alerts_sdf.write.format("delta").mode("overwrite").saveAsTable(table_name("alerts"))
    print(f"\n✅ Written {len(alerts)} alerts to {table_name('alerts')}")
else:
    print("\n⚠️ No alerts generated.")