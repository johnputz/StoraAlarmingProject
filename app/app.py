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
    """Get alerts with session-state mutations applied."""
    if "alerts" not in st.session_state:
        st.session_state["alerts"] = load_csv("alerts")
    return st.session_state["alerts"]

def get_suppressions():
    """Get suppressions including session-state additions."""
    if "suppressions" not in st.session_state:
        st.session_state["suppressions"] = load_csv("suppressions")
    return st.session_state["suppressions"]

def get_notification_config():
    """Get notification config with session-state mutations."""
    if "notification_config" not in st.session_state:
        st.session_state["notification_config"] = load_csv("notification_config")
    return st.session_state["notification_config"]

def get_rules():
    """Get rules with session-state mutations."""
    if "rules" not in st.session_state:
        st.session_state["rules"] = load_csv("rules")
    return st.session_state["rules"]

def update_alert(alert_id, **kwargs):
    """Update an alert in session state."""
    alerts = get_alerts()
    mask = alerts["alert_id"] == alert_id
    for key, value in kwargs.items():
        alerts.loc[mask, key] = value
    st.session_state["alerts"] = alerts

# --- Page Config ---
st.set_page_config(
    page_title="Stora Resource Health Monitor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Sidebar Navigation ---
st.sidebar.title("⚡ Stora Health Monitor")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Resource Detail", "Rules Management", "Notification Config", "Issue Log"],
    index=0
)

# --- Load Common Data ---
@st.cache_data
def load_resources():
    return load_csv("resources")

def load_alerts():
    return get_alerts()

def load_rules():
    return get_rules()


# ============================================================
# PAGE: DASHBOARD (Status Tiles)
# ============================================================
def page_dashboard():
    st.title("📊 Resource Health Dashboard")
    st.markdown("Real-time status of all managed resources. Click a resource for details.")
    
    resources = load_resources()
    alerts = load_alerts()
    
    # Calculate status per resource
    open_alerts = alerts[alerts["status"] == "OPEN"] if not alerts.empty else pd.DataFrame()
    
    # Filter controls
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        type_filter = st.multiselect("Resource Type", ["solar", "battery", "hybrid"], default=["solar", "battery", "hybrid"])
    with col_f2:
        status_filter = st.multiselect("Status", ["GREEN", "YELLOW", "RED"], default=["GREEN", "YELLOW", "RED"])
    with col_f3:
        st.markdown(f"**Last evaluated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    st.markdown("---")
    
    # Resource tiles
    cols = st.columns(len(resources))
    for idx, (_, res) in enumerate(resources.iterrows()):
        if res["resource_type"] not in type_filter:
            continue
        
        # Determine status
        res_alerts = open_alerts[open_alerts["resource_id"] == res["resource_id"]] if not open_alerts.empty else pd.DataFrame()
        red_count = len(res_alerts[res_alerts["severity"] == "RED"]) if not res_alerts.empty else 0
        yellow_count = len(res_alerts[res_alerts["severity"] == "YELLOW"]) if not res_alerts.empty else 0
        
        if red_count > 0:
            status = "RED"
            status_color = "#FF4B4B"
            status_emoji = "🔴"
        elif yellow_count > 0:
            status = "YELLOW"
            status_color = "#FFA500"
            status_emoji = "🟡"
        else:
            status = "GREEN"
            status_color = "#00CC66"
            status_emoji = "🟢"
        
        if status not in status_filter:
            continue
        
        # Type icon
        type_icons = {"solar": "☀️", "battery": "🔋", "hybrid": "⚡"}
        type_icon = type_icons.get(res["resource_type"], "❓")
        
        with cols[idx]:
            st.markdown(f"""
            <div style="
                border: 3px solid {status_color};
                border-radius: 12px;
                padding: 20px;
                text-align: center;
                background: linear-gradient(135deg, {status_color}15, {status_color}05);
            ">
                <h2 style="margin:0;">{status_emoji}</h2>
                <h3 style="margin:5px 0; height: 2.8em; display:flex; align-items:center; justify-content:center;">{type_icon} {res['resource_name']}</h3>
                <p style="color: gray; margin:2px 0;">{res['resource_type'].title()} | {res['nameplate_mw']:.0f} MW</p>
                <p style="color: gray; margin:2px 0;">{res['client_name']}</p>
                <hr style="margin: 10px 0;">
                <p style="font-size: 1.1em;"><b>Active Alerts:</b> 
                    <span style="color: #FF4B4B;">{red_count} RED</span> | 
                    <span style="color: #FFA500;">{yellow_count} YLW</span>
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"Details →", key=f"detail_{res['resource_id']}"):
                st.session_state["selected_resource"] = res["resource_id"]
                st.session_state["page"] = "Resource Detail"
                st.rerun()
    
    # Summary stats
    st.markdown("---")
    st.subheader("📊 Summary")
    col1, col2, col3, col4 = st.columns(4)
    total_open = len(open_alerts) if not open_alerts.empty else 0
    col1.metric("Total Open Alerts", total_open)
    col2.metric("RED Alerts", red_count if not open_alerts.empty else 0)
    col3.metric("Resources Monitored", len(resources))
    col4.metric("Active Rules", len(load_rules()[load_rules()["is_active"] == True]) if not load_rules().empty else 0)


# ============================================================
# PAGE: RESOURCE DETAIL (Drill-Down)
# ============================================================
def page_resource_detail():
    st.title("🔍 Resource Detail")
    
    resources = load_resources()
    alerts = load_alerts()
    
    # Resource selector
    selected_id = st.session_state.get("selected_resource", resources.iloc[0]["resource_id"] if not resources.empty else None)
    resource_options = {f"{r['resource_name']} ({r['resource_type']})": r["resource_id"] for _, r in resources.iterrows()}
    
    selected_label = st.selectbox(
        "Select Resource",
        list(resource_options.keys()),
        index=list(resource_options.values()).index(selected_id) if selected_id in resource_options.values() else 0
    )
    selected_id = resource_options[selected_label]
    res = resources[resources["resource_id"] == selected_id].iloc[0]
    
    # Resource info header
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Type", res["resource_type"].title())
    col2.metric("Nameplate", f"{res['nameplate_mw']} MW")
    col3.metric("Capacity", f"{res['capacity_mwh'] or 'N/A'} MWh")
    col4.metric("Node", res["node"])
    
    st.markdown(f"**Client:** {res['client_name']} | **ISO:** {res['iso']}")
    st.markdown("---")
    
    # Active alerts for this resource
    res_alerts = alerts[alerts["resource_id"] == selected_id] if not alerts.empty else pd.DataFrame()
    open_alerts = res_alerts[res_alerts["status"] == "OPEN"] if not res_alerts.empty else pd.DataFrame()
    
    st.subheader(f"🚨 Active Alerts ({len(open_alerts)})")
    
    if not open_alerts.empty:
        for idx, alert in open_alerts.iterrows():
            severity_color = "#FF4B4B" if alert["severity"] == "RED" else "#FFA500"
            severity_icon = "🔴" if alert["severity"] == "RED" else "🟡"
            
            with st.expander(f"{severity_icon} [{alert['severity']}] {alert['message']}", expanded=True):
                st.markdown(f"**Rule:** {alert['rule_id']} | **Triggered:** {alert['triggered_at']} | **Operating Date:** {alert['operating_date']} HE{alert.get('hour_ending', 'N/A')}")
                
                # Show details
                if alert.get("details_json"):
                    try:
                        details = json.loads(alert["details_json"])
                        st.json(details)
                    except:
                        pass
                
                # Get recommended action from rules
                rules = load_rules()
                rule_info = rules[rules["rule_id"] == alert["rule_id"]]
                if not rule_info.empty:
                    st.info(f"💡 **Recommended Action:** {rule_info.iloc[0]['recommended_action']}")
                
                # Action buttons
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    if st.button("✅ Acknowledge", key=f"ack_{alert['alert_id']}"):
                        run_update(f"""
                            UPDATE {table_name('alerts')}
                            SET status = 'ACKNOWLEDGED', 
                                acknowledged_by = 'current_user',
                                acknowledged_at = current_timestamp()
                            WHERE alert_id = '{alert['alert_id']}'
                        """)
                        st.success("Alert acknowledged!")
                        st.rerun()
                with col_b:
                    if st.button("✔️ Resolve", key=f"res_{alert['alert_id']}"):
                        st.session_state[f"resolving_{alert['alert_id']}"] = True
                with col_c:
                    if st.button("🚫 Suppress", key=f"sup_{alert['alert_id']}"):
                        st.session_state[f"suppressing_{alert['alert_id']}"] = True
                
                # Resolution form
                if st.session_state.get(f"resolving_{alert['alert_id']}"):
                    notes = st.text_area("Resolution notes:", key=f"notes_{alert['alert_id']}")
                    if st.button("Submit Resolution", key=f"submit_res_{alert['alert_id']}"):
                        run_update(f"""
                            UPDATE {table_name('alerts')}
                            SET status = 'RESOLVED',
                                resolved_by = 'current_user',
                                resolved_at = current_timestamp(),
                                resolution_notes = '{notes}'
                            WHERE alert_id = '{alert['alert_id']}'
                        """)
                        st.session_state[f"resolving_{alert['alert_id']}"] = False
                        st.success("Alert resolved!")
                        st.rerun()
                
                # Suppression form
                if st.session_state.get(f"suppressing_{alert['alert_id']}"):
                    supp_duration = st.selectbox(
                        "Suppress for:",
                        ["24 hours", "7 days", "30 days", "Permanently"],
                        key=f"supp_dur_{alert['alert_id']}"
                    )
                    supp_reason = st.text_input("Reason:", key=f"supp_reason_{alert['alert_id']}")
                    if st.button("Confirm Suppression", key=f"submit_sup_{alert['alert_id']}"):
                        if supp_duration == "Permanently":
                            expires = "NULL"
                        elif supp_duration == "24 hours":
                            expires = f"current_timestamp() + INTERVAL 1 DAY"
                        elif supp_duration == "7 days":
                            expires = f"current_timestamp() + INTERVAL 7 DAYS"
                        else:
                            expires = f"current_timestamp() + INTERVAL 30 DAYS"
                        
                        import uuid
                        supp_id = str(uuid.uuid4())
                        run_update(f"""
                            INSERT INTO {table_name('suppressions')}
                            VALUES ('{supp_id}', '{alert['rule_id']}', '{selected_id}',
                                    'current_user', current_timestamp(), {expires}, '{supp_reason}')
                        """)
                        run_update(f"""
                            UPDATE {table_name('alerts')}
                            SET status = 'SUPPRESSED'
                            WHERE alert_id = '{alert['alert_id']}'
                        """)
                        st.session_state[f"suppressing_{alert['alert_id']}"] = False
                        st.success(f"Rule {alert['rule_id']} suppressed for this resource!")
                        st.rerun()
    else:
        st.success("✅ No active alerts for this resource. All clear!")
    
    # Historical alert log
    st.markdown("---")
    st.subheader("📋 Alert History")
    if not res_alerts.empty:
        # Filter controls
        col1, col2 = st.columns(2)
        with col1:
            hist_severity = st.multiselect("Severity", ["RED", "YELLOW"], default=["RED", "YELLOW"], key="hist_sev")
        with col2:
            hist_status = st.multiselect("Status", ["OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"], 
                                        default=["OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"], key="hist_stat")
        
        filtered = res_alerts[
            (res_alerts["severity"].isin(hist_severity)) &
            (res_alerts["status"].isin(hist_status))
        ]
        st.dataframe(filtered[["triggered_at", "severity", "rule_id", "message", "status", "resolution_notes"]], 
                    use_container_width=True, hide_index=True)
    else:
        st.info("No alert history for this resource.")


# ============================================================
# PAGE: RULES MANAGEMENT
# ============================================================
def page_rules_management():
    st.title("⚙️ Rules Management")
    st.markdown("Create, edit, and manage alerting rules.")
    
    rules = load_rules()
    
    # Tabs for list vs. create
    tab1, tab2, tab3, tab4 = st.tabs(["📜 Active Rules", "➕ Create Rule", "🔍 Backtest Rule", "🧠 AI Rule Builder"])
    
    with tab1:
        if not rules.empty:
            for _, rule in rules.iterrows():
                status_icon = "✅" if rule["is_active"] else "❌"
                severity_badge = f"🔴 {rule['severity']}" if rule["severity"] == "RED" else f"🟡 {rule['severity']}"
                
                with st.expander(f"{status_icon} {rule['rule_id']}: {rule['rule_name']} [{severity_badge}]"):
                    st.markdown(f"**Condition:** `{rule['condition_expression']}`")
                    st.markdown(f"**Action:** {rule['recommended_action']}")
                    st.markdown(f"**Applies to:** {rule['applies_to_types']}")
                    st.markdown(f"**Created:** {rule['created_at']} by {rule['created_by']}")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if rule["is_active"]:
                            if st.button(f"Disable", key=f"disable_{rule['rule_id']}"):
                                rules_df = get_rules()
                                rules_df.loc[rules_df["rule_id"] == rule["rule_id"], "is_active"] = False
                                st.session_state["rules"] = rules_df
                                st.success(f"Rule {rule['rule_id']} disabled.")
                                st.rerun()
                        else:
                            if st.button(f"Enable", key=f"enable_{rule['rule_id']}"):
                                rules_df = get_rules()
                                rules_df.loc[rules_df["rule_id"] == rule["rule_id"], "is_active"] = True
                                st.session_state["rules"] = rules_df
                                st.success(f"Rule {rule['rule_id']} enabled.")
                                st.rerun()
    
    with tab2:
        st.subheader("Create New Rule")
        resources_list = load_resources()
        with st.form("new_rule_form"):
            rule_id = st.text_input("Rule ID (e.g., E6, D3, S4)")
            rule_name = st.text_input("Rule Name")
            severity = st.selectbox("Severity", ["RED", "YELLOW"])
            market = st.selectbox("Market", ["DA", "RT", "AS"])
            condition = st.text_area("Condition Expression", 
                                   placeholder="e.g., actual_mw > 5 AND da_lmp < -30 AND soc_pct < 15")
            action = st.text_area("Recommended Action",
                                placeholder="What should the operator do when this rule fires?")
            
            # Rule Assignment Scope
            st.markdown("---")
            st.markdown("🎯 **Rule Assignment Scope**")
            assignment_mode = st.radio(
                "Apply this rule to:",
                ["All resources", "By resource type", "Specific resource(s)"],
                horizontal=True
            )
            
            applies_to_types = []
            assigned_resources = []
            if assignment_mode == "By resource type":
                applies_to_types = st.multiselect("Select resource types", 
                    ["battery", "solar", "hybrid"], default=["battery", "hybrid"])
            elif assignment_mode == "Specific resource(s)":
                resource_options = list(resources_list["resource_name"].values)
                assigned_resources = st.multiselect("Select resources", resource_options, key="rule_resources")
            
            submitted = st.form_submit_button("Create Rule")
            if submitted and rule_id and rule_name and condition:
                if assignment_mode == "All resources":
                    applies_str = "battery,solar,hybrid"
                    resource_ids_str = "ALL"
                elif assignment_mode == "By resource type":
                    applies_str = ",".join(applies_to_types) if applies_to_types else "battery,solar,hybrid"
                    resource_ids_str = "ALL"
                else:
                    applies_str = "battery,solar,hybrid"
                    if assigned_resources:
                        res_ids = [resources_list[resources_list['resource_name']==rn]['resource_id'].values[0] 
                                  for rn in assigned_resources]
                        resource_ids_str = ",".join(res_ids)
                    else:
                        resource_ids_str = "ALL"
                
                rules_df = get_rules()
                new_rule = pd.DataFrame([{
                    "rule_id": rule_id, "rule_name": rule_name, "severity": severity,
                    "condition_expression": condition, "recommended_action": action,
                    "applies_to_types": applies_str, "is_active": True,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(), "created_by": "user",
                    "resource_ids": resource_ids_str
                }])
                st.session_state["rules"] = pd.concat([rules_df, new_rule], ignore_index=True)
                scope_msg = "All resources" if resource_ids_str == "ALL" else \
                           f"Types: {applies_str}" if assignment_mode == "By resource type" else \
                           f"Resources: {', '.join(assigned_resources)}"
                st.success(f"Rule {rule_id} created! Scope: {scope_msg}")
                st.rerun()
    
    with tab3:
        st.subheader("🔍 Backtest Rule Against Historical Data")
        st.markdown("""
        Select a rule and a date to verify it would have fired as expected.
        This validates rule logic against historical data before putting it into production.
        """)
        
        rules_for_bt = get_rules()
        if not rules_for_bt.empty:
            rule_options = {f"{r['rule_id']}: {r['rule_name']}": r['rule_id'] for _, r in rules_for_bt.iterrows()}
            selected_rule_label = st.selectbox("Select Rule to Backtest", list(rule_options.keys()))
            selected_rule_id = rule_options[selected_rule_label]
            
            col1, col2 = st.columns(2)
            with col1:
                backtest_date = st.date_input("Operating Date", value=pd.Timestamp("2025-07-03"))
            with col2:
                backtest_resource = st.selectbox("Resource (optional)", 
                    ["All Resources"] + list(load_resources()["resource_name"].values),
                    key="bt_resource")
            
            if st.button("▶️ Run Backtest"):
                # Check alerts for this rule/date combination
                alerts = get_alerts()
                bt_alerts = alerts[alerts["rule_id"] == selected_rule_id].copy()
                
                if "operating_date" in bt_alerts.columns:
                    bt_alerts["operating_date"] = pd.to_datetime(bt_alerts["operating_date"]).dt.date
                    bt_alerts = bt_alerts[bt_alerts["operating_date"] == backtest_date]
                
                if backtest_resource != "All Resources":
                    res_id = load_resources()[load_resources()["resource_name"] == backtest_resource]["resource_id"].values[0]
                    bt_alerts = bt_alerts[bt_alerts["resource_id"] == res_id]
                
                st.markdown("---")
                if not bt_alerts.empty:
                    st.success(f"✅ Rule **{selected_rule_id}** fired **{len(bt_alerts)} time(s)** on {backtest_date}:")
                    for _, alert in bt_alerts.iterrows():
                        severity_icon = "🔴" if alert["severity"] == "RED" else "🟡"
                        st.markdown(f"{severity_icon} **HE{int(alert['hour_ending']) if pd.notna(alert.get('hour_ending')) else 'N/A'}:** {alert['message']}")
                        if alert.get("details_json") and pd.notna(alert["details_json"]):
                            try:
                                st.json(json.loads(alert["details_json"]))
                            except:
                                pass
                else:
                    st.warning(f"⚠️ Rule **{selected_rule_id}** did NOT fire on {backtest_date}" + 
                              (f" for {backtest_resource}" if backtest_resource != "All Resources" else "") +
                              ". Check if the conditions were met in the data for this date.")
                    
                    # Show what the data looked like on that date for context
                    st.markdown("**Data snapshot for this date (for debugging):**")
                    prices = load_csv("prices")
                    prices["operating_date"] = pd.to_datetime(prices["operating_date"]).dt.date
                    day_prices = prices[prices["operating_date"] == backtest_date]
                    if not day_prices.empty:
                        st.line_chart(day_prices.groupby("hour_ending")["da_lmp"].mean(), 
                                     use_container_width=True)
                        st.caption("Average DA LMP across nodes for this date")
    
    with tab4:
        st.subheader("🧠 Natural Language Rule Builder")
        st.markdown("""
        Describe a rule in plain English and AI will translate it into a structured rule definition.
        You can review and edit before activating.
        """)
        
        nl_input = st.text_area(
            "Describe your rule:",
            placeholder="e.g., Flag any battery that is discharging more than 20 MW when prices are below -$30 and it has less than 15% charge remaining",
            height=100
        )
        
        if st.button("🔄 Translate to Rule", disabled=not nl_input):
            # Simulated AI translation (in production, this would call an LLM)
            st.markdown("---")
            st.markdown("**🤖 AI Interpretation:**")
            
            # Simple pattern matching for demo purposes
            st.info("""
            **Parsed Rule:**
            - **Name:** Custom discharge at negative price rule
            - **Severity:** RED
            - **Condition:** `actual_mw > 20 AND da_lmp < -30 AND soc_pct < 15`
            - **Applies to:** battery, hybrid
            - **Action:** Investigate immediately - resource is discharging significant energy at negative prices with critically low state of charge.
            """)
            st.warning("⚠️ This is a prototype. In production, an LLM (e.g., DBRX, GPT-4) would parse the natural language into the structured rule format.")
            
            if st.button("✅ Accept and Create This Rule"):
                st.success("Rule created! (Demo mode - would write to rules table in production)")


# ============================================================
# PAGE: NOTIFICATION CONFIG
# ============================================================
def page_notification_config():
    st.title("🔔 Notification Configuration")
    st.markdown("Configure email notifications for alerts.")
    
    configs = get_notification_config()
    resources = load_resources()
    
    # Existing configs
    st.subheader("Current Notification Rules")
    if not configs.empty:
        for _, config in configs.iterrows():
            res_name = "All Resources" if pd.isna(config.get("resource_id")) or config["resource_id"] is None else \
                resources[resources["resource_id"] == config["resource_id"]]["resource_name"].values[0] \
                if config["resource_id"] in resources["resource_id"].values else config["resource_id"]
            
            status_icon = "✅" if config["is_active"] else "❌"
            with st.expander(f"{status_icon} {res_name} — Notify on {config['severity_threshold']}+"):
                st.markdown(f"**Email List:** {config['email_list']}")
                st.markdown(f"**Threshold:** {config['severity_threshold']} and above")
                st.markdown(f"**Active:** {config['is_active']}")
                
                if st.button("Toggle Active", key=f"toggle_{config['config_id']}"):
                    new_state = "false" if config["is_active"] else "true"
                    run_update(f"""
                        UPDATE {table_name('notification_config')}
                        SET is_active = {new_state}
                        WHERE config_id = '{config['config_id']}'
                    """)
                    st.rerun()
    
    # Add new config
    st.markdown("---")
    st.subheader("➕ Add Notification Rule")
    with st.form("new_notif_form"):
        res_options = ["All Resources"] + list(resources["resource_name"].values)
        selected_res = st.selectbox("Resource", res_options)
        severity_threshold = st.selectbox("Notify on severity", ["RED", "YELLOW"])
        email_list = st.text_input("Email addresses (comma-separated)",
                                  placeholder="ops@company.com, manager@company.com")
        
        if st.form_submit_button("Add Notification Rule"):
            import uuid
            config_id = f"NOTIF-{str(uuid.uuid4())[:8]}"
            res_id = "NULL" if selected_res == "All Resources" else \
                f"'{resources[resources['resource_name'] == selected_res]['resource_id'].values[0]}'"
            
            run_update(f"""
                INSERT INTO {table_name('notification_config')}
                VALUES ('{config_id}', {res_id}, '{severity_threshold}', '{email_list}', true)
            """)
            st.success("Notification rule added!")
            st.rerun()


# ============================================================
# PAGE: ISSUE LOG
# ============================================================
def page_issue_log():
    st.title("📋 Issue Log")
    st.markdown("Complete audit trail of all alerts and their resolution status.")
    
    alerts = load_alerts()
    resources = load_resources()
    
    if alerts.empty:
        st.info("No alerts recorded yet. Run the rules engine to generate alerts.")
        return
    
    # Filters
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        filter_severity = st.multiselect("Severity", ["RED", "YELLOW"], default=["RED", "YELLOW"], key="log_sev")
    with col2:
        filter_status = st.multiselect("Status", ["OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"],
                                      default=["OPEN", "ACKNOWLEDGED"], key="log_stat")
    with col3:
        filter_resource = st.multiselect("Resource", list(resources["resource_name"].values),
                                        default=list(resources["resource_name"].values), key="log_res")
    with col4:
        filter_rule = st.multiselect("Rule", list(alerts["rule_id"].unique()), 
                                    default=list(alerts["rule_id"].unique()), key="log_rule")
    
    # Map resource names back to IDs for filtering
    selected_res_ids = resources[resources["resource_name"].isin(filter_resource)]["resource_id"].values
    
    filtered = alerts[
        (alerts["severity"].isin(filter_severity)) &
        (alerts["status"].isin(filter_status)) &
        (alerts["resource_id"].isin(selected_res_ids)) &
        (alerts["rule_id"].isin(filter_rule))
    ]
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Shown", len(filtered))
    col2.metric("Open", len(filtered[filtered["status"] == "OPEN"]))
    col3.metric("Resolved", len(filtered[filtered["status"] == "RESOLVED"]))
    col4.metric("Suppressed", len(filtered[filtered["status"] == "SUPPRESSED"]))
    
    # Merge resource names for display
    display_df = filtered.merge(resources[["resource_id", "resource_name"]], on="resource_id", how="left")
    
    st.dataframe(
        display_df[["triggered_at", "severity", "resource_name", "rule_id", "message", "status", "resolution_notes"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "triggered_at": "Triggered",
            "severity": "Severity",
            "resource_name": "Resource",
            "rule_id": "Rule",
            "message": "Message",
            "status": "Status",
            "resolution_notes": "Resolution Notes"
        }
    )


# ============================================================
# MAIN ROUTER
# ============================================================
# Override page from session state if set by button click
if "page" in st.session_state:
    page = st.session_state["page"]
    del st.session_state["page"]

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
