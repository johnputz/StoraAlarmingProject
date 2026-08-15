"""Stora Resource Health Monitoring Dashboard
A Streamlit-based prototype for monitoring battery and solar resource health.
Data is loaded from bundled CSV files (no SQL warehouse or UC permissions required).
Mutations (acknowledge, resolve, suppress) persist in session state for the demo.
"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os
import uuid as uuid_mod
from pathlib import Path
import altair as alt

# --- Data Layer (local CSV + session state) ---
DATA_DIR = Path(__file__).parent / "data"

@st.cache_data
def load_csv(name):
    """Load a CSV file from the bundled data directory."""
    path = DATA_DIR / f"{name}.csv"
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()

def get_alerts():
    if "alerts" not in st.session_state:
        st.session_state["alerts"] = load_csv("alerts")
    return st.session_state["alerts"]

def get_suppressions():
    if "suppressions" not in st.session_state:
        st.session_state["suppressions"] = load_csv("suppressions")
    return st.session_state["suppressions"]

def get_notification_config():
    if "notification_config" not in st.session_state:
        st.session_state["notification_config"] = load_csv("notification_config")
    return st.session_state["notification_config"]

def get_rules():
    if "rules" not in st.session_state:
        st.session_state["rules"] = load_csv("rules")
    return st.session_state["rules"]

def update_alert(alert_id, **kwargs):
    alerts = get_alerts()
    mask = alerts["alert_id"] == alert_id
    for key, value in kwargs.items():
        alerts.loc[mask, key] = value
    st.session_state["alerts"] = alerts

# --- Page Config ---
st.set_page_config(
    page_title="Stora Resource Health Monitor",
    page_icon="\u26a1",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Sidebar Navigation (with persistent page state) ---
st.sidebar.title("\u26a1 Stora Health Monitor")
st.sidebar.markdown("---")

PAGES = ["Dashboard", "Resource Detail", "Rules Management", "Notification Config", "Issue Log"]

# Initialize page state
if "current_page" not in st.session_state:
    st.session_state["current_page"] = "Dashboard"

# Track previous page for back navigation
if "previous_page" not in st.session_state:
    st.session_state["previous_page"] = "Dashboard"

# If a button set "page", sync to current_page AND to the radio widget key
if "page" in st.session_state:
    st.session_state["previous_page"] = st.session_state["current_page"]
    st.session_state["current_page"] = st.session_state.pop("page")
    st.session_state["nav_radio"] = st.session_state["current_page"]

page = st.sidebar.radio(
    "Navigation", PAGES,
    index=PAGES.index(st.session_state["current_page"]),
    key="nav_radio"
)
# Sidebar click updates current_page
if page != st.session_state["current_page"]:
    st.session_state["previous_page"] = st.session_state["current_page"]
st.session_state["current_page"] = page

# --- Load Common Data ---
@st.cache_data
def load_resources():
    return load_csv("resources")

def load_alerts():
    return get_alerts()

def load_rules():
    return get_rules()


# --- Investigation Chart Builder ---
def render_investigation_chart(alert, resource_id, resources):
    rule_id = alert["rule_id"]
    op_date = str(alert["operating_date"])[:10]
    res_info = resources[resources["resource_id"] == resource_id].iloc[0]
    node = res_info["node"]
    nameplate = res_info["nameplate_mw"]

    all_alerts = get_alerts()
    fired_alerts = all_alerts[
        (all_alerts["rule_id"] == rule_id) &
        (all_alerts["resource_id"] == resource_id) &
        (all_alerts["operating_date"].astype(str).str[:10] == op_date)
    ]
    fired_hours = set(fired_alerts["hour_ending"].dropna().astype(int).values)
    highlight_df = pd.DataFrame([{"hour_start": h - 0.5, "hour_end": h + 0.5} for h in fired_hours])

    st.markdown(f"### \U0001f50d Investigation: {rule_id} on {op_date}")
    st.markdown(f"**Resource:** {res_info['resource_name']} | **Fired hours:** HE {', '.join(str(h) for h in sorted(fired_hours))}")

    if rule_id.startswith("E") and rule_id != "E4":
        _render_energy_chart(resource_id, node, op_date, highlight_df)
    elif rule_id == "E4":
        _render_bid_chart(resource_id, op_date)
    elif rule_id.startswith("D"):
        _render_dispatch_chart(resource_id, op_date, highlight_df, nameplate)
    elif rule_id.startswith("S"):
        _render_soc_chart(resource_id, op_date, highlight_df)
    else:
        st.info("No investigation chart available for this rule type.")


def _render_energy_chart(resource_id, node, op_date, highlight_df):
    meter = load_csv("meter_reads")
    meter["timestamp"] = pd.to_datetime(meter["timestamp"])
    meter["operating_date"] = meter["timestamp"].dt.strftime("%Y-%m-%d")
    meter["hour_ending"] = meter["timestamp"].dt.hour.replace(0, 24)
    meter_day = meter[(meter["resource_id"] == resource_id) & (meter["operating_date"] == op_date)]

    prices = load_csv("prices")
    prices_day = prices[(prices["node"] == node) & (prices["operating_date"] == op_date)]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Actual Generation (MW)**")
        if not meter_day.empty:
            chart_data = meter_day[["hour_ending", "actual_mw"]].rename(columns={"hour_ending": "HE", "actual_mw": "MW"})
            base = alt.Chart(chart_data).mark_line(point=True, color="#1f77b4").encode(
                x=alt.X("HE:Q", scale=alt.Scale(domain=[1, 24])), y="MW:Q")
            layers = [base]
            if not highlight_df.empty:
                layers.insert(0, alt.Chart(highlight_df).mark_rect(opacity=0.2, color="red").encode(x="hour_start:Q", x2="hour_end:Q"))
            st.altair_chart(alt.layer(*layers).properties(height=250), use_container_width=True)

    with col2:
        st.markdown("**LMP Prices ($/MWh)**")
        if not prices_day.empty:
            price_long = prices_day.melt(id_vars=["hour_ending"], value_vars=["da_lmp", "rt_lmp"],
                                         var_name="Market", value_name="Price")
            price_long["Market"] = price_long["Market"].map({"da_lmp": "DA LMP", "rt_lmp": "RT LMP"})
            price_long = price_long.rename(columns={"hour_ending": "HE"})
            base = alt.Chart(price_long).mark_line(point=True).encode(
                x=alt.X("HE:Q", scale=alt.Scale(domain=[1, 24])), y="Price:Q", color="Market:N")
            layers = [base]
            if not highlight_df.empty:
                layers.insert(0, alt.Chart(highlight_df).mark_rect(opacity=0.2, color="red").encode(x="hour_start:Q", x2="hour_end:Q"))
            st.altair_chart(alt.layer(*layers).properties(height=250), use_container_width=True)

    st.caption("Red bands = hours when rule fired.")


def _render_bid_chart(resource_id, op_date):
    bids = load_csv("bids")
    awards = load_csv("awards")
    bids_day = bids[(bids["resource_id"] == resource_id) & (bids["operating_date"] == op_date)]
    awards_day = awards[(awards["resource_id"] == resource_id) & (awards["operating_date"] == op_date)]

    st.markdown("**Bids and Awards for this Operating Date**")
    if bids_day.empty:
        st.error(f"\u26a0\ufe0f **No bids found for {op_date}** \u2014 confirms the E4 rule fired correctly.")
    else:
        bid_chart = bids_day[["hour_ending", "bid_mw"]].rename(columns={"hour_ending": "HE", "bid_mw": "MW"})
        bid_chart["Type"] = "Bid"
        chart_data = bid_chart
        if not awards_day.empty:
            award_chart = awards_day[["hour_ending", "awarded_mw"]].rename(columns={"hour_ending": "HE", "awarded_mw": "MW"})
            award_chart["Type"] = "Award"
            chart_data = pd.concat([bid_chart, award_chart])
        base = alt.Chart(chart_data).mark_bar(opacity=0.7).encode(
            x="HE:O", y="MW:Q", color="Type:N", xOffset="Type:N").properties(height=300)
        st.altair_chart(base, use_container_width=True)


def _render_dispatch_chart(resource_id, op_date, highlight_df, nameplate):
    meter = load_csv("meter_reads")
    meter["timestamp"] = pd.to_datetime(meter["timestamp"])
    meter["operating_date"] = meter["timestamp"].dt.strftime("%Y-%m-%d")
    meter["hour_ending"] = meter["timestamp"].dt.hour.replace(0, 24)
    meter_day = meter[(meter["resource_id"] == resource_id) & (meter["operating_date"] == op_date)]

    dispatch = load_csv("dispatch_instructions")
    dispatch_day = dispatch[(dispatch["resource_id"] == resource_id) & (dispatch["operating_date"] == op_date)].copy()
    dispatch_day["timestamp"] = pd.to_datetime(dispatch_day["timestamp"])
    dispatch_day["hour_ending"] = dispatch_day["timestamp"].dt.hour.replace(0, 24)

    st.markdown("**Actual vs Dispatch Instructions (MW)**")
    chart_parts = []
    if not meter_day.empty:
        m = meter_day[["hour_ending", "actual_mw"]].rename(columns={"hour_ending": "HE", "actual_mw": "MW"})
        m["Series"] = "Actual (Meter)"
        chart_parts.append(m)
    if not dispatch_day.empty:
        d = dispatch_day[["hour_ending", "instructed_mw"]].rename(columns={"hour_ending": "HE", "instructed_mw": "MW"})
        d["Series"] = "Dispatch Instruction"
        chart_parts.append(d)

    if chart_parts:
        chart_data = pd.concat(chart_parts)
        base = alt.Chart(chart_data).mark_line(point=True).encode(
            x=alt.X("HE:Q", scale=alt.Scale(domain=[1, 24])), y="MW:Q", color="Series:N")
        cap_line = alt.Chart(pd.DataFrame({"y": [nameplate]})).mark_rule(strokeDash=[4,4], color="gray").encode(y="y:Q")
        layers = [base, cap_line]
        if not highlight_df.empty:
            layers.insert(0, alt.Chart(highlight_df).mark_rect(opacity=0.2, color="red").encode(x="hour_start:Q", x2="hour_end:Q"))
        st.altair_chart(alt.layer(*layers).properties(height=300), use_container_width=True)
        st.caption(f"Dashed line = nameplate ({nameplate} MW). Red bands = fired hours.")


def _render_soc_chart(resource_id, op_date, highlight_df):
    soc = load_csv("soc_readings")
    soc["timestamp"] = pd.to_datetime(soc["timestamp"])
    soc["operating_date"] = soc["timestamp"].dt.strftime("%Y-%m-%d")
    soc["hour_ending"] = soc["timestamp"].dt.hour.replace(0, 24)
    soc_day = soc[(soc["resource_id"] == resource_id) & (soc["operating_date"] == op_date)]

    if soc_day.empty:
        st.warning("No SOC data available for this date.")
        return

    st.markdown("**State of Charge (%)**")
    chart_data = soc_day[["hour_ending", "soc_pct"]].rename(columns={"hour_ending": "HE", "soc_pct": "SOC %"})
    base = alt.Chart(chart_data).mark_area(opacity=0.4, line=True, color="#2ca02c").encode(
        x=alt.X("HE:Q", scale=alt.Scale(domain=[1, 24])),
        y=alt.Y("SOC %:Q", scale=alt.Scale(domain=[0, 100])))
    layers = [base]
    if not highlight_df.empty:
        layers.insert(0, alt.Chart(highlight_df).mark_rect(opacity=0.25, color="red").encode(x="hour_start:Q", x2="hour_end:Q"))
    st.altair_chart(alt.layer(*layers).properties(height=300), use_container_width=True)
    st.caption("Red bands = hours rule fired. Green = SOC level.")


# ============================================================
# PAGE: DASHBOARD
# ============================================================
def page_dashboard():
    st.title("\U0001f4ca Resource Health Dashboard")
    st.markdown("Real-time status of all managed resources. Click a resource for details.")
    
    with st.expander("ℹ️ How to use this Dashboard", expanded=False):
        st.markdown("""
        - **Tiles** show each resource's current health: 🟢 Green = no issues, 🟡 Yellow = warnings, 🔴 Red = critical alerts
        - **Resource Type** filter: show/hide resources by type (solar, battery, hybrid)
        - **Status** filter: show/hide tiles by their health color
        - **Rule Type** filter: toggle between Day-Ahead (DA) and Real-Time (RT) rules — DA rules can be evaluated before the operating day; RT rules require actuals/telemetry
        - Click **Details →** on any tile to drill into that resource's alerts and take action
        """)

    resources = load_resources()
    alerts = load_alerts()
    open_alerts = alerts[alerts["status"] == "OPEN"] if not alerts.empty else pd.DataFrame()

    # Filters
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    with col_f1:
        type_filter = st.multiselect("Resource Type", ["solar", "battery", "hybrid"],
                                     default=["solar", "battery", "hybrid"])
    with col_f2:
        status_filter = st.multiselect("Status", ["GREEN", "YELLOW", "RED"],
                                       default=["GREEN", "YELLOW", "RED"])
    with col_f3:
        data_req_filter = st.multiselect("Rule Type", ["DA", "RT"], default=["DA", "RT"],
                                         help="DA = Day-Ahead only, RT = Requires real-time/actuals")
    with col_f4:
        st.markdown(f"**Last evaluated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Apply DA/RT filter to alerts
    rules = load_rules()
    if "data_requirement" in rules.columns:
        matching_rule_ids = set(rules[rules["data_requirement"].isin(data_req_filter)]["rule_id"].values)
    else:
        matching_rule_ids = set(rules["rule_id"].values)
    if not open_alerts.empty:
        open_alerts = open_alerts[open_alerts["rule_id"].isin(matching_rule_ids)]

    # Show filter summary when non-default
    if set(data_req_filter) != {"DA", "RT"}:
        st.info(f"\U0001f50d **Filtered to {', '.join(data_req_filter)} rules only** \u2014 {len(open_alerts)} matching open alerts")

    st.markdown("---")

    # Resource tiles
    filtered_resources = resources[resources["resource_type"].isin(type_filter)]
    cols = st.columns(max(len(filtered_resources), 1))
    for idx, (_, res) in enumerate(filtered_resources.iterrows()):
        res_alerts = open_alerts[open_alerts["resource_id"] == res["resource_id"]] if not open_alerts.empty else pd.DataFrame()
        red_count = len(res_alerts[res_alerts["severity"] == "RED"]) if not res_alerts.empty else 0
        yellow_count = len(res_alerts[res_alerts["severity"] == "YELLOW"]) if not res_alerts.empty else 0

        if red_count > 0:
            status, status_color, status_emoji = "RED", "#FF4B4B", "\U0001f534"
        elif yellow_count > 0:
            status, status_color, status_emoji = "YELLOW", "#FFA500", "\U0001f7e1"
        else:
            status, status_color, status_emoji = "GREEN", "#00CC66", "\U0001f7e2"

        if status not in status_filter:
            continue

        type_icons = {"solar": "\u2600\ufe0f", "battery": "\U0001f50b", "hybrid": "\u26a1"}
        type_icon = type_icons.get(res["resource_type"], "\u2753")

        with cols[idx]:
            st.markdown(f"""
            <div style="border: 3px solid {status_color}; border-radius: 12px; padding: 20px;
                        text-align: center; background: linear-gradient(135deg, {status_color}15, {status_color}05);">
                <h2 style="margin:0;">{status_emoji}</h2>
                <h3 style="margin:5px 0; height:2.8em; display:flex; align-items:center; justify-content:center;">{type_icon} {res['resource_name']}</h3>
                <p style="color:gray; margin:2px 0;">{res['resource_type'].title()} | {res['nameplate_mw']:.0f} MW</p>
                <p style="color:gray; margin:2px 0;">{res['client_name']}</p>
                <hr style="margin:10px 0;">
                <p style="font-size:1.1em;"><b>Active Alerts:</b>
                    <span style="color:#FF4B4B;">{red_count} RED</span> |
                    <span style="color:#FFA500;">{yellow_count} YLW</span></p>
            </div>
            """, unsafe_allow_html=True)

            if st.button("Details \u2192", key=f"detail_{res['resource_id']}"):
                st.session_state["selected_resource"] = res["resource_id"]
                st.session_state["page"] = "Resource Detail"
                st.rerun()

    # Summary
    st.markdown("---")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Open Alerts", len(open_alerts))
    col2.metric("RED Alerts", len(open_alerts[open_alerts["severity"] == "RED"]) if not open_alerts.empty else 0)
    col3.metric("Resources Monitored", len(resources))
    col4.metric("Active Rules", len(rules[rules["is_active"] == True]) if not rules.empty else 0)


# ============================================================
# PAGE: RESOURCE DETAIL
# ============================================================
def page_resource_detail():
    if st.button("\u2190 Back", help="Return to previous page"):
        st.session_state["page"] = st.session_state.get("previous_page", "Dashboard")
        st.rerun()
    st.title("\U0001f50d Resource Detail")
    
    with st.expander("ℹ️ How to use Resource Detail", expanded=False):
        st.markdown("""
        - **Select a resource** from the dropdown to view its alerts
        - Each alert expander shows the rule that fired, when, and recommended actions
        - **Action buttons:**
            - ✅ **Acknowledge** — mark that you've seen the alert (stays open for resolution)
            - ✔️ **Resolve** — close the alert with resolution notes
            - 🚫 **Suppress** — silence this rule for this resource for a set duration
            - 🔍 **Investigate** — expand a time-series chart showing the data around the alert with fired hours highlighted in red
        """)

    resources = load_resources()
    alerts = load_alerts()

    selected_id = st.session_state.get("selected_resource", resources.iloc[0]["resource_id"] if not resources.empty else None)
    resource_options = {f"{r['resource_name']} ({r['resource_type']})": r["resource_id"] for _, r in resources.iterrows()}
    selected_label = st.selectbox("Select Resource", list(resource_options.keys()),
        index=list(resource_options.values()).index(selected_id) if selected_id in resource_options.values() else 0)
    selected_id = resource_options[selected_label]
    res = resources[resources["resource_id"] == selected_id].iloc[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Type", res["resource_type"].title())
    col2.metric("Nameplate", f"{res['nameplate_mw']} MW")
    col3.metric("Capacity", f"{res['capacity_mwh'] or 'N/A'} MWh")
    col4.metric("Node", res["node"])
    st.markdown(f"**Client:** {res['client_name']} | **ISO:** {res['iso']}")
    st.markdown("---")

    res_alerts = alerts[alerts["resource_id"] == selected_id] if not alerts.empty else pd.DataFrame()
    open_alerts = res_alerts[res_alerts["status"] == "OPEN"] if not res_alerts.empty else pd.DataFrame()

    st.subheader(f"\U0001f6a8 Active Alerts ({len(open_alerts)})")

    if not open_alerts.empty:
        for idx, alert in open_alerts.iterrows():
            severity_icon = "\U0001f534" if alert["severity"] == "RED" else "\U0001f7e1"
            with st.expander(f"{severity_icon} [{alert['severity']}] {alert['message']}", expanded=True):
                st.markdown(f"**Rule:** {alert['rule_id']} | **Triggered:** {alert['triggered_at']} | **Date:** {alert['operating_date']} HE{alert.get('hour_ending', 'N/A')}")

                if alert.get("details_json") and pd.notna(alert.get("details_json")):
                    try:
                        st.json(json.loads(alert["details_json"]))
                    except:
                        pass

                rules = load_rules()
                rule_info = rules[rules["rule_id"] == alert["rule_id"]]
                if not rule_info.empty:
                    st.info(f"\U0001f4a1 **Recommended Action:** {rule_info.iloc[0]['recommended_action']}")

                # Action buttons
                col_a, col_b, col_c, col_d = st.columns(4)
                with col_a:
                    if st.button("\u2705 Acknowledge", key=f"ack_{alert['alert_id']}"):
                        update_alert(alert['alert_id'], status='ACKNOWLEDGED',
                                    acknowledged_by='current_user', acknowledged_at=datetime.now().isoformat())
                        st.rerun()
                with col_b:
                    if st.button("\u2714\ufe0f Resolve", key=f"res_{alert['alert_id']}"):
                        st.session_state[f"resolving_{alert['alert_id']}"] = True
                with col_c:
                    if st.button("\U0001f6ab Suppress", key=f"sup_{alert['alert_id']}"):
                        st.session_state[f"suppressing_{alert['alert_id']}"] = True
                with col_d:
                    if st.button("\U0001f50d Investigate", key=f"inv_{alert['alert_id']}"):
                        st.session_state[f"investigating_{alert['alert_id']}"] = \
                            not st.session_state.get(f"investigating_{alert['alert_id']}", False)

                # Investigation chart
                if st.session_state.get(f"investigating_{alert['alert_id']}", False):
                    st.markdown("---")
                    render_investigation_chart(alert, selected_id, resources)
                    st.markdown("---")

                # Resolution form
                if st.session_state.get(f"resolving_{alert['alert_id']}"):
                    notes = st.text_area("Resolution notes:", key=f"notes_{alert['alert_id']}")
                    if st.button("Submit Resolution", key=f"submit_res_{alert['alert_id']}"):
                        update_alert(alert['alert_id'], status='RESOLVED',
                                    resolved_by='current_user', resolved_at=datetime.now().isoformat(),
                                    resolution_notes=notes)
                        st.session_state[f"resolving_{alert['alert_id']}"] = False
                        st.success("Alert resolved!")
                        st.rerun()

                # Suppression form
                if st.session_state.get(f"suppressing_{alert['alert_id']}"):
                    supp_duration = st.selectbox("Suppress for:", ["24 hours", "7 days", "30 days", "Permanently"],
                                                key=f"supp_dur_{alert['alert_id']}")
                    supp_reason = st.text_input("Reason:", key=f"supp_reason_{alert['alert_id']}")
                    if st.button("Confirm Suppression", key=f"submit_sup_{alert['alert_id']}"):
                        update_alert(alert['alert_id'], status='SUPPRESSED')
                        supps = get_suppressions()
                        new_supp = pd.DataFrame([{
                            "suppression_id": str(uuid_mod.uuid4()), "rule_id": alert['rule_id'],
                            "resource_id": selected_id, "suppressed_by": "current_user",
                            "suppressed_at": datetime.now().isoformat(),
                            "expires_at": None if supp_duration == "Permanently" else
                                (datetime.now() + timedelta(days=1 if supp_duration == "24 hours" else 7 if supp_duration == "7 days" else 30)).isoformat(),
                            "reason": supp_reason
                        }])
                        st.session_state["suppressions"] = pd.concat([supps, new_supp], ignore_index=True)
                        st.session_state[f"suppressing_{alert['alert_id']}"] = False
                        st.success(f"Rule {alert['rule_id']} suppressed!")
                        st.rerun()
    else:
        st.success("\u2705 No active alerts for this resource. All clear!")

    # Historical log
    st.markdown("---")
    st.subheader("\U0001f4cb Alert History")
    if not res_alerts.empty:
        st.dataframe(res_alerts[["triggered_at", "severity", "rule_id", "message", "status"]],
                    use_container_width=True, hide_index=True)


# ============================================================
# PAGE: RULES MANAGEMENT
# ============================================================
def page_rules_management():
    if st.button("\u2190 Back", key="back_rules", help="Return to previous page"):
        st.session_state["page"] = st.session_state.get("previous_page", "Dashboard")
        st.rerun()
    st.title("\u2699\ufe0f Rules Management")
    rules = load_rules()

    with st.expander("ℹ️ How to use Rules Management", expanded=False):
        st.markdown("""
        - **Active Rules** — view, filter (DA/RT), and enable/disable existing rules
        - **Create Rule** — define a new rule with severity, data requirement (DA vs RT), condition expression, and assignment scope (all resources, by type, or specific resources)
        - **Backtest Rule** — pick a rule + date to verify it fires correctly against historical data. Great for validating new rules before going live.
        - **AI Rule Builder** — describe a rule in plain English (placeholder for production LLM integration)
        """)

    tab1, tab2, tab3, tab4 = st.tabs(["\U0001f4dc Active Rules", "\u2795 Create Rule", "\U0001f50d Backtest Rule", "\U0001f9e0 AI Rule Builder"])

    with tab1:
        # DA/RT filter
        rules_filter = st.multiselect("Filter by Rule Type", ["DA", "RT"], default=["DA", "RT"],
                                      help="DA = Day-Ahead only, RT = Real-time", key="rules_tab_filter")
        if not rules.empty:
            display_rules = rules[rules["data_requirement"].isin(rules_filter)] if "data_requirement" in rules.columns else rules
            for _, rule in display_rules.iterrows():
                status_icon = "\u2705" if rule["is_active"] else "\u274c"
                sev_badge = "\U0001f534 RED" if rule["severity"] == "RED" else "\U0001f7e1 YELLOW"
                dr_badge = "\U0001f4c5 DA" if rule.get("data_requirement") == "DA" else "\u23f1\ufe0f RT"

                with st.expander(f"{status_icon} {rule['rule_id']}: {rule['rule_name']} [{sev_badge}] [{dr_badge}]"):
                    st.markdown(f"**Data Requirement:** {'\U0001f4c5 Day-Ahead' if rule.get('data_requirement') == 'DA' else '\u23f1\ufe0f Real-Time'}")
                    st.markdown(f"**Condition:** `{rule['condition_expression']}`")
                    st.markdown(f"**Action:** {rule['recommended_action']}")
                    st.markdown(f"**Applies to:** {rule['applies_to_types']}")
                    resource_ids = rule.get('resource_ids', 'ALL')
                    st.markdown(f"**Resources:** {'All' if pd.isna(resource_ids) or resource_ids == 'ALL' else resource_ids}")

                    if rule["is_active"]:
                        if st.button("Disable", key=f"disable_{rule['rule_id']}"):
                            r = get_rules()
                            r.loc[r["rule_id"] == rule["rule_id"], "is_active"] = False
                            st.session_state["rules"] = r
                            st.rerun()
                    else:
                        if st.button("Enable", key=f"enable_{rule['rule_id']}"):
                            r = get_rules()
                            r.loc[r["rule_id"] == rule["rule_id"], "is_active"] = True
                            st.session_state["rules"] = r
                            st.rerun()

    with tab2:
        st.subheader("Create New Rule")
        resources_list = load_resources()
        with st.form("new_rule_form"):
            rule_id = st.text_input("Rule ID (e.g., E6, D3, S4)")
            rule_name = st.text_input("Rule Name")
            severity = st.selectbox("Severity", ["RED", "YELLOW"])
            data_requirement = st.selectbox("Data Requirement", ["DA", "RT"],
                help="DA = evaluable from DA data alone; RT = requires real-time actuals")
            condition = st.text_area("Condition Expression",
                placeholder="e.g., actual_mw > 5 AND da_lmp < -30 AND soc_pct < 15")
            action = st.text_area("Recommended Action")

            st.markdown("---")
            st.markdown("\U0001f3af **Rule Assignment Scope**")
            assignment_mode = st.radio("Apply to:", ["All resources", "By resource type", "Specific resource(s)"], horizontal=True)
            applies_to_types, assigned_resources = [], []
            if assignment_mode == "By resource type":
                applies_to_types = st.multiselect("Types", ["battery", "solar", "hybrid"], default=["battery", "hybrid"])
            elif assignment_mode == "Specific resource(s)":
                assigned_resources = st.multiselect("Resources", list(resources_list["resource_name"].values), key="rule_resources")

            if st.form_submit_button("Create Rule") and rule_id and rule_name and condition:
                applies_str = ",".join(applies_to_types) if applies_to_types else "battery,solar,hybrid"
                if assigned_resources:
                    res_ids = [resources_list[resources_list['resource_name']==rn]['resource_id'].values[0] for rn in assigned_resources]
                    resource_ids_str = ",".join(res_ids)
                else:
                    resource_ids_str = "ALL"
                new_rule = pd.DataFrame([{
                    "rule_id": rule_id, "rule_name": rule_name, "severity": severity,
                    "condition_expression": condition, "recommended_action": action,
                    "applies_to_types": applies_str, "is_active": True,
                    "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(),
                    "created_by": "user", "resource_ids": resource_ids_str, "data_requirement": data_requirement
                }])
                st.session_state["rules"] = pd.concat([get_rules(), new_rule], ignore_index=True)
                st.success(f"Rule {rule_id} created!")
                st.rerun()

    with tab3:
        st.subheader("\U0001f50d Backtest Rule Against Historical Data")
        st.markdown("Select a rule and a date to verify it fires correctly against historical data.")
        rules_for_bt = get_rules()
        if not rules_for_bt.empty:
            rule_options = {f"{r['rule_id']}: {r['rule_name']}": r['rule_id'] for _, r in rules_for_bt.iterrows()}
            selected_rule_label = st.selectbox("Select Rule", list(rule_options.keys()))
            selected_rule_id = rule_options[selected_rule_label]
            col1, col2 = st.columns(2)
            with col1:
                backtest_date = st.date_input("Operating Date", value=pd.Timestamp("2025-07-04"))
            with col2:
                backtest_resource = st.selectbox("Resource", ["All Resources"] + list(load_resources()["resource_name"].values), key="bt_res")

            if st.button("\u25b6\ufe0f Run Backtest"):
                bt_alerts = get_alerts()[get_alerts()["rule_id"] == selected_rule_id].copy()
                if "operating_date" in bt_alerts.columns:
                    bt_alerts["operating_date"] = pd.to_datetime(bt_alerts["operating_date"]).dt.date
                    bt_alerts = bt_alerts[bt_alerts["operating_date"] == backtest_date]
                if backtest_resource != "All Resources":
                    res_id = load_resources()[load_resources()["resource_name"] == backtest_resource]["resource_id"].values[0]
                    bt_alerts = bt_alerts[bt_alerts["resource_id"] == res_id]

                if not bt_alerts.empty:
                    st.success(f"\u2705 Rule **{selected_rule_id}** fired **{len(bt_alerts)} time(s)** on {backtest_date}")
                    for _, a in bt_alerts.iterrows():
                        st.markdown(f"{'\U0001f534' if a['severity']=='RED' else '\U0001f7e1'} **HE{int(a['hour_ending']) if pd.notna(a.get('hour_ending')) else '?'}:** {a['message']}")
                else:
                    st.warning(f"\u26a0\ufe0f Rule **{selected_rule_id}** did NOT fire on {backtest_date}")

    with tab4:
        st.subheader("\U0001f9e0 Natural Language Rule Builder")
        st.markdown("Describe a rule in plain English and AI will translate it. *(Placeholder for production LLM integration.)*")
        nl_input = st.text_area("Describe your rule:", placeholder="e.g., Flag any battery discharging >20 MW when prices < -$30 with <15% SOC")
        if st.button("\U0001f504 Translate to Rule", disabled=not nl_input):
            st.info("**Parsed Rule:** Custom discharge rule | RED | `actual_mw > 20 AND da_lmp < -30 AND soc_pct < 15` | battery, hybrid")
            st.warning("\u26a0\ufe0f Prototype placeholder. Production would use an LLM.")


# ============================================================
# PAGE: NOTIFICATION CONFIG
# ============================================================
def page_notification_config():
    if st.button("\u2190 Back", key="back_notif", help="Return to previous page"):
        st.session_state["page"] = st.session_state.get("previous_page", "Dashboard")
        st.rerun()
    st.title("\U0001f514 Notification Configuration")
    configs = get_notification_config()
    resources = load_resources()

    with st.expander("ℹ️ How notifications work", expanded=False):
        st.markdown("""
        - **Notification rules** define who gets emailed when alerts fire
        - Set a **severity threshold** — "RED" means only critical alerts notify; "YELLOW" means warnings too
        - Assign to **All Resources** or a specific resource
        - Toggle rules on/off without deleting them
        """)

    st.subheader("Current Notification Rules")
    if not configs.empty:
        for _, config in configs.iterrows():
            res_name = "All Resources" if pd.isna(config.get("resource_id")) else config["resource_id"]
            status_icon = "\u2705" if config["is_active"] else "\u274c"
            with st.expander(f"{status_icon} {res_name} \u2014 Notify on {config['severity_threshold']}+"):
                st.markdown(f"**Email:** {config['email_list']} | **Active:** {config['is_active']}")
                if st.button("Toggle Active", key=f"toggle_{config['config_id']}"):
                    cfg = get_notification_config()
                    cfg.loc[cfg["config_id"] == config["config_id"], "is_active"] = not config["is_active"]
                    st.session_state["notification_config"] = cfg
                    st.rerun()

    st.markdown("---")
    st.subheader("\u2795 Add Notification Rule")
    with st.form("new_notif_form"):
        res_options = ["All Resources"] + list(resources["resource_name"].values)
        selected_res = st.selectbox("Resource", res_options)
        severity_threshold = st.selectbox("Notify on severity", ["RED", "YELLOW"])
        email_list = st.text_input("Email addresses (comma-separated)")
        if st.form_submit_button("Add Notification Rule"):
            cfg = get_notification_config()
            new_cfg = pd.DataFrame([{
                "config_id": f"NOTIF-{str(uuid_mod.uuid4())[:8]}",
                "resource_id": None if selected_res == "All Resources" else
                    resources[resources["resource_name"] == selected_res]["resource_id"].values[0],
                "severity_threshold": severity_threshold, "email_list": email_list, "is_active": True
            }])
            st.session_state["notification_config"] = pd.concat([cfg, new_cfg], ignore_index=True)
            st.success("Notification rule added!")
            st.rerun()


# ============================================================
# PAGE: ISSUE LOG
# ============================================================
def page_issue_log():
    if st.button("\u2190 Back", key="back_log", help="Return to previous page"):
        st.session_state["page"] = st.session_state.get("previous_page", "Dashboard")
        st.rerun()
    st.title("\U0001f4cb Issue Log")
    alerts = load_alerts()
    resources = load_resources()
    
    with st.expander("ℹ️ How to use the Issue Log", expanded=False):
        st.markdown("""
        - **Filterable audit trail** of all alerts across all resources
        - Use **Market** filter (DA/RT) to focus on specific market types — e.g., filter to DA + weekend dates to review Monday morning
        - Use **Status** filter to find unresolved alerts or review past resolutions
        - Use **Rule** filter to isolate alerts from specific rules
        """)
    
    if alerts.empty:
        st.info("No alerts recorded.")
        return

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        filter_severity = st.multiselect("Severity", ["RED", "YELLOW"], default=["RED", "YELLOW"], key="log_sev")
    with col2:
        filter_status = st.multiselect("Status", ["OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"],
                                      default=["OPEN", "ACKNOWLEDGED"], key="log_stat")
    with col3:
        filter_resource = st.multiselect("Resource", list(resources["resource_name"].values),
                                        default=list(resources["resource_name"].values), key="log_res")
    with col4:
        available_markets = list(alerts["market"].dropna().unique()) if "market" in alerts.columns else ["DA", "RT"]
        filter_market = st.multiselect("Market", available_markets, default=available_markets, key="log_mkt")
    with col5:
        filter_rule = st.multiselect("Rule", list(alerts["rule_id"].unique()),
                                    default=list(alerts["rule_id"].unique()), key="log_rule")

    selected_res_ids = resources[resources["resource_name"].isin(filter_resource)]["resource_id"].values
    filtered = alerts[
        (alerts["severity"].isin(filter_severity)) &
        (alerts["status"].isin(filter_status)) &
        (alerts["resource_id"].isin(selected_res_ids)) &
        (alerts["rule_id"].isin(filter_rule))
    ]
    if "market" in filtered.columns:
        filtered = filtered[filtered["market"].isin(filter_market)]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Shown", len(filtered))
    col2.metric("Open", len(filtered[filtered["status"] == "OPEN"]))
    col3.metric("Resolved", len(filtered[filtered["status"] == "RESOLVED"]))
    col4.metric("Suppressed", len(filtered[filtered["status"] == "SUPPRESSED"]))

    display_df = filtered.merge(resources[["resource_id", "resource_name"]], on="resource_id", how="left")
    display_cols = ["triggered_at", "severity", "resource_name", "rule_id", "message", "status"]
    if "market" in display_df.columns:
        display_cols.insert(3, "market")
    st.dataframe(display_df[[c for c in display_cols if c in display_df.columns]],
                use_container_width=True, hide_index=True)


# ============================================================
# MAIN ROUTER
# ============================================================
if page == "Dashboard":
    page_dashboard()
elif page == "Resource Detail":
    page_resource_detail()
elif page == "Rules Management":
    page_rules_management()
elif page == "Notification Config":
    page_notification_config()
elif page == "Issue Log":
    page_issue_log()
