# Stora Resource Health Monitoring & Alarming System
## Project Scope & Implementation Plan — v1 (Draft)

**Date:** 2026-08-14  
**Author:** John Putz  
**Status:** Preliminary / Discovery  

---

## 1. Executive Summary

Build a configurable, rules-based health-status dashboard that monitors battery and solar resources managed on behalf of clients in ISO/RTO markets (primarily CAISO). The system ingests bid submissions, market awards, dispatch instructions, and meter data from the Stora bidding application and associated data feeds, evaluates resource behavior against a set of business rules, and surfaces discrepancies as color-coded alerts (green / yellow / red) on a per-resource dashboard. Users can drill down into issues, acknowledge/resolve them, suppress future recurrences, and receive email notifications for urgent items.

---

## 2. Goals & Objectives

1. **Early detection** of resource operational anomalies (e.g., generating at deeply negative prices, failure to follow dispatch, charge/discharge outside expected SOC bounds).
2. **Actionable guidance** — each alert includes a description of the issue and recommended next steps / troubleshooting path.
3. **Configurability** — rules can be added, modified, or retired over time without code changes to the core platform.
4. **Accountability** — full issue log with timestamps, acknowledgments, and resolution notes; audit trail of rule changes.
5. **Proactive notification** — configurable email (and potentially Slack/Teams) alerts for yellow and red status changes.
6. **Shareability** — prototype with simulated data that stakeholders can interact with to validate UX and rule logic before production build.

---

## 3. Scope Boundaries

### In Scope (Phase 1 / Prototype)
* Dashboard UI showing per-resource status tiles (green/yellow/red)
* Drill-down view per resource showing active issues, historical log
* Rules engine with a small starter set of example rules (see §5)
* Simulated/synthetic data representing bids, awards, dispatch, meter, SOC
* Issue lifecycle: create → acknowledge → resolve / suppress
* Email notification stub (prototype sends to a test list)
* Rule CRUD interface (add / edit / disable rules)

### In Scope (Production — future)
* Live integration with Stora bid-submission database
* Live integration with CAISO award feeds (OASIS / MRI-S / API)
* Live integration with dispatch instruction feeds
* Live integration with meter/telemetry data (PI / SCADA / historian)
* Live SOC tracking from BMS or Stora internal state
* Multi-ISO support (CAISO initially; extensible to SPP, ERCOT, etc.)
* Role-based access (operators vs. managers vs. clients)
* SLA / uptime requirements

### Out of Scope
* Modifications to the Stora bidding engine itself
* Financial settlement reconciliation (separate system)
* Physical plant control actions (this system is observe + alert only)

---

## 4. Key Concepts & Definitions

| Term | Definition |
|------|------------|
| Resource | A battery or solar generator asset participating in an ISO market |
| Stora | The bidding application that creates and submits DA and RT bids |
| DA | Day-Ahead market (bids submitted day before operating day) |
| RT / HA | Real-Time / Hourly market (bids submitted intra-day) |
| SOC | State of Charge (battery % of capacity) |
| LMP | Locational Marginal Price (clearing price at a node) |
| AS | Ancillary Services (Spin, Reg Up/Down, Imbalance Reserves, etc.) |
| Award | Market operator confirmation that a bid has been accepted |
| Dispatch | ISO instruction to a resource to increase/decrease output |
| Meter | Actual measured output/consumption of the resource |
| Rule | A logical condition that, when triggered, generates an alert |
| Alert | An instance of a rule firing for a specific resource at a specific time |
| Suppression | User action to silence a specific alert pattern for a resource |

---

## 5. Rules Engine — Starter Rule Set (Examples)

Each rule has: **ID, Name, Severity (Yellow/Red), Condition Logic, Recommended Action, Applies-To (resource types)**.

### Energy Market Rules

| # | Rule | Severity | Condition | Action |
|---|------|----------|-----------|--------|
| E1 | Generating at negative prices (low SOC) | RED | Resource is generating AND LMP < -$20 AND SOC < 10% | Investigate immediately — resource should not be discharging at negative prices with minimal stored energy. Check Stora bid logic and dispatch compliance. |
| E2 | Generating at negative prices (high SOC) | YELLOW | Resource is generating AND LMP < -$50 AND SOC > 50% | Review — may be intentional (AS obligation or ramp constraint) but warrants verification. |
| E3 | Charging at high positive prices | YELLOW | Resource is charging AND LMP > $200 | Verify whether charge is from an AS award or a bidding error. |
| E4 | Bid not submitted | RED | No DA bid record found for resource for upcoming operating day by T-1 14:00 | Stora may have failed to submit. Check Stora logs and resubmit manually if needed. |
| E5 | Award significantly above/below bid | YELLOW | Awarded MW differs from bid MW by > 20% at the awarded price point | Possible data issue or partial award — verify with ISO award file. |

### Dispatch & Compliance Rules

| # | Rule | Severity | Condition | Action |
|---|------|----------|-----------|--------|
| D1 | Dispatch not followed | RED | abs(Meter MW - Dispatch MW) > tolerance (e.g., 5 MW or 10%) for > 5 min | Resource is non-compliant. Check plant status, communications, and inverter faults. |
| D2 | Dispatch exceeds capacity | YELLOW | Dispatch instruction MW > nameplate or > SOC-feasible MW | ISO may have stale parameters. File ticket to update resource limits. |

### Ancillary Services Rules

| # | Rule | Severity | Condition | Action |
|---|------|----------|-----------|--------|
| A1 | AS award but resource unavailable | RED | Resource has AS award for interval AND (resource offline OR SOC insufficient to provide service) | Potential non-performance penalty. Investigate plant status. |
| A2 | AS capacity test failed | YELLOW | Resource failed to respond to AGC signal within required timeframe | Check inverter response settings and communications latency. |

### SOC / Operational Rules

| # | Rule | Severity | Condition | Action |
|---|------|----------|-----------|--------|
| S1 | SOC out of expected bounds | YELLOW | SOC < 5% or SOC > 95% outside of expected charge/discharge window | May indicate metering drift or unexpected cycling. |
| S2 | SOC flatline | YELLOW | SOC unchanged for > 4 hours despite active awards | Possible meter/BMS communication failure. |
| S3 | Throughput exceeds daily limit | YELLOW | Cumulative daily MWh throughput > contractual or warranty limit | Alert asset manager — may need to curtail to protect warranty. |

---

## 6. Data Model (Conceptual)

### Input Data Streams

```
┌─────────────────────────────────────────────────────────┐
│                     DATA SOURCES                         │
├─────────────────┬───────────────────────────────────────┤
│ Bids            │ DA bids, RT bids (from Stora DB)      │
│ Awards          │ DA awards, RT awards (from CAISO)     │
│ Prices          │ DA LMP, RT LMP, AS prices (CAISO)     │
│ Dispatch        │ Dispatch instructions (CAISO / ADS)   │
│ Meter           │ Actual generation/load (telemetry)    │
│ SOC             │ Battery state-of-charge (BMS / Stora) │
│ Resource Config │ Nameplate, capacity, node, limits     │
└─────────────────┴───────────────────────────────────────┘
```

### Core Tables (Prototype Schema)

```
resources
  resource_id (PK), resource_name, resource_type (battery|solar),
  iso, node, nameplate_mw, capacity_mwh, client_name

bids
  bid_id (PK), resource_id (FK), market (DA|RT), operating_date,
  hour_ending, bid_mw, bid_price, bid_type (supply|demand), product (energy|spin|reg_up|...),
  submitted_at

awards
  award_id (PK), resource_id (FK), market, operating_date,
  hour_ending, awarded_mw, clearing_price, product

dispatch_instructions
  dispatch_id (PK), resource_id (FK), operating_date,
  timestamp, instructed_mw, duration_min

meter_reads
  meter_id (PK), resource_id (FK), timestamp,
  actual_mw, interval_seconds

soc_readings
  soc_id (PK), resource_id (FK), timestamp,
  soc_pct, soc_mwh

rules
  rule_id (PK), rule_name, severity (RED|YELLOW),
  condition_expression, recommended_action, applies_to_types,
  is_active, created_at, updated_at, created_by

alerts
  alert_id (PK), rule_id (FK), resource_id (FK),
  triggered_at, operating_date, hour_ending,
  severity, message, details_json,
  status (OPEN|ACKNOWLEDGED|RESOLVED|SUPPRESSED),
  acknowledged_by, acknowledged_at,
  resolved_by, resolved_at, resolution_notes

suppressions
  suppression_id (PK), rule_id (FK), resource_id (FK),
  created_by, created_at, expires_at (NULL = permanent),
  reason

notification_config
  config_id (PK), resource_id (FK, nullable = all resources),
  severity_threshold (YELLOW|RED), email_list, is_active
```

---

## 7. Architecture — High Level

```
┌──────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  Data Sources │────▶│  Ingestion Layer  │────▶│  Evaluation Engine  │
│  (Stora, CAISO,│     │  (scheduled ETL /  │     │  (rules engine,     │
│   BMS, Meter)  │     │   streaming)       │     │   runs on schedule  │
│               │     │                    │     │   or event-trigger)  │
└──────────────┘     └──────────────────┘     └─────────┬──────────┘
                                                         │
                                                         ▼
                                              ┌──────────────────────┐
                                              │   Alert Store (Delta) │
                                              │   + Rule Config       │
                                              └─────────┬────────────┘
                                                         │
                                    ┌────────────────────┼────────────────────┐
                                    │                    │                    │
                                    ▼                    ▼                    ▼
                          ┌──────────────┐    ┌──────────────────┐   ┌────────────────┐
                          │  Dashboard   │    │  Notification    │   │  Issue Log /   │
                          │  (status     │    │  Service (email) │   │  Audit Trail   │
                          │   tiles)     │    │                  │   │                │
                          └──────────────┘    └──────────────────┘   └────────────────┘
```

### Technology Options (to be decided)

| Component | Prototype | Production Candidates |
|-----------|-----------|----------------------|
| Data storage | Delta tables (Databricks) | Delta tables / Lakehouse |
| Rules engine | Python (pandas/Spark eval) | Python + config table; or dedicated rules engine (e.g., business-rules lib) |
| Scheduler | Databricks Job (cron) | Databricks Job or event-driven (Kafka trigger) |
| Dashboard | Databricks App (Dash/Streamlit) or AI/BI Dashboard | Databricks App, Power BI, custom web app |
| Notifications | Python smtplib / SendGrid stub | SendGrid, Azure Logic Apps, or PagerDuty |
| Rule management | Notebook UI or simple CRUD app | Admin UI within the dashboard app |

---

## 8. User Interactions

### Dashboard Home View
* Grid/panel of resource tiles, each showing:
  - Resource name and type icon (battery / solar)
  - Current status color (green / yellow / red)
  - Count of active alerts
  - Last-evaluated timestamp
* Filter/sort by: status, resource type, client, ISO

### Resource Drill-Down View
* Resource details (name, node, capacity, client)
* Active alerts list with severity, rule name, time triggered, recommended action
* Historical alert log (filterable by date range, severity, rule)
* Actions: Acknowledge, Resolve (with notes), Suppress (with expiry option)

### Rule Management View (Admin)
* List of all rules with status (active/inactive)
* Create new rule: name, severity, condition builder, action text, applicable resource types
* **Natural-language rule authoring:** User describes a rule in plain English (e.g., "flag any battery that is discharging when prices are below -$30 and it has less than 15% charge left"). An AI model translates the description into a structured rule definition (condition expression, severity, recommended action, applicable resource types). The user reviews a human-readable summary of what the AI produced, confirms or edits, then activates. This lowers the barrier for operators and asset managers to create rules without needing to understand the underlying condition syntax.
* Edit / disable existing rules
* Version history of rule changes

### Notification Settings
* Per-resource or global notification preferences
* Email list management
* Severity threshold (notify on RED only, or YELLOW+RED)

---

## 9. Implementation Plan

### Phase 0 — Discovery & Requirements Gathering (2-3 weeks)

| # | Task | Owner | Notes |
|---|------|-------|-------|
| 0.1 | Identify all resources in scope (names, types, ISOs, nodes) | TBD | Which batteries and solar assets does Stora currently bid? Full inventory. |
| 0.2 | Document Stora database schema for bids/awards | TBD | What tables/APIs does Stora expose? Format, latency, access method. |
| 0.3 | Document CAISO data feeds for awards, dispatch, meter | TBD | MRI-S, CMRI, ADS, OASIS — which feeds are already ingested vs. new? |
| 0.4 | Identify SOC data source | TBD | Is SOC available from Stora internal state, BMS API, or PI historian? What granularity? |
| 0.5 | Interview operators: what issues do they currently catch manually? | TBD | Informs rule priority and ensures we're not duplicating existing monitoring. |
| 0.6 | Define user roles and access requirements | TBD | Who views, who edits rules, who receives notifications? |
| 0.7 | Review existing alerting/monitoring (if any) | TBD | Avoid duplication with plant-level SCADA alarms or ISO penalty dashboards. |
| 0.8 | Confirm notification requirements | TBD | Email only? Slack/Teams? PagerDuty integration? Escalation paths? |
| 0.9 | Legal/compliance review | TBD | Any restrictions on storing/displaying ISO data externally? Client data segregation? |

### Phase 1 — Prototype with Simulated Data (3-4 weeks)

| # | Task | Notes |
|---|------|-------|
| 1.1 | Design simulated data generator | Python script that produces realistic bid/award/dispatch/meter/SOC data for 3-5 resources over a 7-day window. Include deliberate anomalies that should trigger rules. |
| 1.2 | Implement core data model (Delta tables) | Create the prototype schema tables in a dev catalog. |
| 1.3 | Build rules engine v1 | Python module that reads rules from config table, evaluates against current data window, writes alerts. |
| 1.4 | Implement starter rule set | Code the ~10 example rules from §5. |
| 1.5 | Build dashboard UI (Databricks App or AI/BI Dashboard) | Status tiles, drill-down, issue log. |
| 1.6 | Implement issue lifecycle (acknowledge / resolve / suppress) | Backend logic + UI controls. |
| 1.7 | Implement notification stub | Sends test emails on alert creation. |
| 1.8 | Implement rule CRUD interface | Simple UI for adding/editing rules. |
| 1.9 | Demo to stakeholders, gather feedback | Iterate on rules, UX, and priorities. |

### Phase 2 — Production Integration (6-8 weeks)

| # | Task | Notes |
|---|------|-------|
| 2.1 | Connect live bid data from Stora | ETL or direct query integration. |
| 2.2 | Connect live award data from CAISO feeds | Leverage existing ingestion pipelines where available. |
| 2.3 | Connect live dispatch data | May require new feed from ADS or CAISO API. |
| 2.4 | Connect live meter/SOC data | Depends on Phase 0 findings (PI, BMS, Stora). |
| 2.5 | Schedule evaluation engine | Cron job or event-trigger; determine evaluation frequency (5-min? hourly?). |
| 2.6 | Harden notification service | Production email provider, retry logic, escalation. |
| 2.7 | Security & access control | Row-level security by client if needed; role-based UI access. |
| 2.8 | Testing & validation | Parallel run: compare automated alerts vs. manual operator catches. |
| 2.9 | Operator training & documentation | User guide, rule-writing guide. |
| 2.10 | Go-live | Phased rollout (1-2 resources first, then full fleet). |

### Phase 3 — Enhancements (ongoing)

* Multi-ISO support (SPP, ERCOT rule variants)
* Machine-learning anomaly detection (complement rules with statistical baselines)
* Mobile-friendly dashboard view
* Client-facing portal (read-only status view for asset owners)
* Integration with ticketing system (Jira, ServiceNow)
* Historical analytics (alert frequency trends, MTTR, resource reliability scoring)

---

## 10. Open Questions & Information Needed

| # | Question | Why It Matters |
|---|----------|----------------|
| Q1 | What is the Stora database platform and how is bid/award data accessed? | Determines integration approach. |
| Q2 | Which CAISO data feeds are already being ingested into existing databases? | Avoid rebuilding what exists. |
| Q3 | What is the SOC data source and its refresh frequency? | SOC is critical for battery rules but may not be in a central DB today. |
| Q4 | How many resources are in scope currently and over the next 12 months? | Affects scale/performance design. |
| Q5 | What is the desired evaluation frequency? (5-min / 15-min / hourly) | Drives architecture (batch vs. near-real-time). |
| Q6 | Who are the primary users and what are their existing tools/workflows? | Drives UX decisions and integration points. |
| Q7 | Are there existing operator runbooks for common issues? | Can seed the "recommended action" text in rules. |
| Q8 | What email/notification infrastructure is available? | Determines notification implementation. |
| Q9 | Are there contractual SLAs for response time to resource issues? | Informs severity thresholds and escalation design. |
| Q10 | Should clients have visibility into the dashboard? | Affects access control and data segregation design. |
| Q11 | Is there a preferred technology stack for the production dashboard? | Databricks App vs. Power BI vs. custom web app. |
| Q12 | What are the AS products currently bid? (Spin, Reg, IR, etc.) | Ensures rule coverage for all relevant products. |

---

## 11. Success Criteria

1. **Prototype:** Stakeholders can interact with the simulated dashboard, understand the alert logic, and provide actionable feedback within 4 weeks.
2. **Production v1:** System catches ≥90% of the operational issues that operators currently identify manually, with <5% false-positive rate (after initial tuning period).
3. **Response time:** Red alerts surface within the evaluation frequency window (e.g., within 15 minutes of the triggering condition).
4. **Adoption:** Operators actively use the tool as their primary monitoring interface within 30 days of go-live.

---

## 12. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| SOC data unavailable or unreliable | Many battery rules depend on SOC | Identify SOC source in Phase 0; design fallback rules that work without SOC |
| Rule noise / alert fatigue | Users ignore the system | Tunable thresholds; suppression feature; severity discipline |
| Data latency | Alerts fire too late to be actionable | Define latency requirements early; design for near-real-time where critical |
| Stora schema changes | Break ingestion | Versioned integration layer with validation checks |
| Scope creep into control actions | Safety/liability risk | Firm scope boundary: observe + alert only, never control |

---

## 13. Next Steps (Immediate)

1. Review this document with stakeholders and confirm scope boundaries.
2. Begin Phase 0 discovery (resource inventory, data source documentation).
3. Identify prototype technology choice (Databricks App vs. AI/BI Dashboard).
4. Assign owners to discovery tasks.
5. Schedule kickoff meeting for prototype development (Phase 1).

---

*This is a living document. Version history will be tracked in the workspace.*
