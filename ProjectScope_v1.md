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

## 13. Stakeholder Feedback (Round 1)

The following requirements emerged from initial prototype review:

### F1: Per-Resource Rule Assignment
Rules should be assignable to specific individual resources (not just by resource type). A rule can apply to one, several, or all resources. The UI should allow multi-select of resources when creating/editing a rule.

### F2: Rule Backtesting
After creating or modifying a rule, the user should be able to navigate to a specific historical date/time and confirm that the rule would have (or did) fire as expected. This validates rule logic before putting it into production monitoring.

### F3: Stora Charting Integration (Production)
When the tool is integrated within Stora, clicking on an alert should take the user to Stora's main charting page, zoomed to the time period when the rule fired, with the chart highlighting where the violation(s) occurred. (Production-only feature; cannot be prototyped without Stora access.)

### F4: Market Filter & After-the-Fact Review
Alerts should be tagged with the market they relate to (DA, RT, AS). Users should be able to filter the issue log and dashboard by market. Key use case: DA rules that fire over the weekend (e.g., DA award anomalies on Saturday/Sunday) need to be easily reviewable on Monday morning — filter by market = DA, date range = weekend, status = OPEN.

---

## 14. Additional Requirements (Surfaced During Prototype Build)

The following requirements emerged during prototype implementation and stakeholder interaction beyond the Round 1 items above:

### F5: DA/RT Data Requirement Classification

Each rule should be labeled with a **data requirement** indicating whether it can be evaluated from Day-Ahead data alone (DA) or requires real-time actuals/telemetry (RT). This classification:
- Appears as a badge on each rule in the Rules Management view (📅 DA or ⏱️ RT)
- Powers a "Rule Type" filter on the Dashboard (so users can view only DA-triggered alerts or only RT-triggered alerts)
- Is set at rule creation time via a dropdown
- Enables the Monday-morning workflow from F4: filter Dashboard to DA-only to review weekend DA anomalies without noise from RT rules that haven't evaluated yet

### F6: Contextual Investigation Charts

Each active alert should have an **Investigate** button that expands an inline time-series chart showing the data context around the alert, with fired hours highlighted. Chart type varies by rule category:
- **Energy rules (E1/E2/E3):** Dual panel — actual generation (MW) + LMP prices (DA and RT), with SOC area chart
- **Bid rules (E4):** Bids vs. awards bar chart for the operating date (or "no bids found" confirmation)
- **Award rules (E5):** Bids vs. awards comparison highlighting discrepancy hours
- **Dispatch rules (D1/D2):** Actual MW vs. dispatch instruction lines + nameplate reference line
- **SOC rules (S1/S2/S3):** SOC percentage area chart + meter activity bars

All charts show red semi-transparent bands on hours when the rule fired. This serves as a lightweight investigation tool in the prototype; in production, it complements F3 (Stora charting deep-link) rather than replacing it.

### F7: Market Tagging on Alerts

Each alert record carries a `market` field (DA or RT) derived from the rule's data requirement classification. This field:
- Powers the Market filter on the Issue Log page
- Enables grouping/sorting alerts by market context
- Supports the F4 use case of filtering to DA-only alerts for weekend review

### F8: E5 Rule — DA Award Exceeds Bid Quantity

Added as a concrete second DA-evaluable rule (complements E4). Fires when the awarded MW for an hour exceeds the bid quantity submitted, indicating a possible data issue or partial/over-award from the ISO. Severity: YELLOW.

### F9: In-Page Navigation (Back Buttons)

All non-Dashboard pages include a "← Back to Dashboard" button at the top for quick return to the hub view. The Dashboard is the central navigation point; the sidebar also provides direct access to any page.

### F10: Contextual Help Expanders

Each page includes a collapsible "ℹ️ How to use..." section (collapsed by default) explaining:
- What the page's filters and controls do
- What the action buttons mean (e.g., Acknowledge vs. Resolve vs. Suppress)
- Workflow tips (e.g., "filter to DA + weekend dates for Monday review")

Designed for first-time users and stakeholder reviewers; experienced users can ignore the collapsed sections.

### F11: Per-Page Tabs in Rules Management

The Rules Management page is organized into four tabs within a single page (not separate pages):
1. **Active Rules** — view, filter (DA/RT), enable/disable
2. **Create Rule** — full rule builder with assignment scope (All / By Type / Specific Resources)
3. **Backtest Rule** — select rule + date to verify historical firing (implements F2)
4. **AI Rule Builder** — natural-language rule authoring placeholder (from §8 original spec)

Navigation between tabs is via clicking the tab headers, not via Back buttons or page navigation.

### F12: Rule Status (Production / Prototype)

Each rule carries a **rule_status** field:
- **Production** — rule is fully active; alerts fire normally and appear on the Dashboard, Resource Detail, and Issue Log.
- **Prototype** — rule is visible in Rules Management (for review, backtesting, and iteration) but does NOT generate alerts. This allows new rules to be defined, discussed, and validated via backtesting before "going live." Promotes clean separation between proven operational rules and experimental ones.

In the Rules Management Active Rules tab, each rule shows a badge: ✅ PROD or 🚧 PROTO. A status filter allows toggling visibility. The Create Rule form defaults new rules to "prototype" so they can be tested before promotion.

Future: a "Promote to Production" button on each prototype rule (with confirmation dialog).

### F13: Rule Author Attribution

Each rule stores a **created_by** (author) field displayed in the Rules Management view. In the prototype:
- Demo rules (E-series): authored by "Homer Simpson"
- Trader-identified rules (T/R-series): authored by "Brian Wynn"

In production, this will default to the currently logged-in user when creating a new rule. The author field supports accountability and makes it easy to identify who to ask about a rule's intent or tuning.

---

## 15. Trader-Identified Rules (Stora Checks Spreadsheet)

The following rules were identified by the trading team from actual operational monitoring needs. Source document: "STORA Checks.xlsx".

### 15.1 Resource Portfolio & Company Filtering

Resources now carry a **company (owner)** field. The Dashboard supports filtering by company so users can isolate a single client's fleet. This also enables a "demo mode" where fictional resources (Burns Industries) can be shown to stakeholders without exposing real client names.

#### Production Resources (Owner: TEA)

| Resource ID | Inferred Type | Site | Nameplate MW |
| --- | --- | --- | --- |
| ARCATA_6_FCPSB1 | BESS | Arcata | 100 |
| ARCATA_6_FCPSB2 | BESS | Arcata | 100 |
| DSFLWR_2_W9CSB2 | BESS | Desert Flower | 100 |
| JANCRK_6_RCABT1 | BESS | January Creek | 100 |
| PUTHCR_1_PCNSB1 | BESS | Putah Creek | 100 |
| KRAMER_1_R1BX3 | BESS (co-located) | Kramer | 100 |
| KRAMER_1_R1PX3 | Solar (co-located) | Kramer | 75 |
| RSMNDS_2_CSRBT1 | BESS (co-located) | Rosamond | 100 |
| RSMNDS_2_CSRSR1 | Solar (co-located) | Rosamond | 75 |
| SANDRN_2_SS1BT1 | BESS (co-located) | San Bernardino | 100 |
| SANDRN_2_SS1SR1 | Solar (co-located) | San Bernardino | 75 |

Co-located sites (Kramer, Rosamond, San Bernardino) have paired BESS + Solar resources at the same facility.

#### Demo Resources (Owner: Burns Industries)

The 4 original Simpsons-themed resources remain for demonstration purposes:
- RES-001 Springfield Solar (solar, 50 MW)
- RES-002 Burns Battery (battery, 100 MW / 400 MWh)
- RES-003 Shelbyville Sun & Store (hybrid, 75 MW / 200 MWh)
- RES-004 Krusty's Clean Energy (hybrid, 60 MW / 150 MWh)

### 15.2 Rules Applying to All Resources

#### T1: Dispatch Following (Enhanced) — RT
**Condition:** Resource actual MW deviates from dispatch instruction by > 10% (or 5 MW, whichever is greater) for 3 or more consecutive 5-minute intervals. Ignore if resource has an active Regulation (REG) award for that interval.
**Inputs:** Awards (to check for REG), generation/meter data (actual MW at POI)
**Intent:** Detect non-compliance before CAISO calls
**Action:** If related to SOC at zero during non-solar hours → submit outage card. Otherwise → contact the plant.
**Note:** This is an enhanced version of the prototype's D1 rule, adding the 3-interval persistence requirement and the REG exclusion.

#### T2: BESS Not Cycling — RT
**Condition:** Battery SOC shows no charge/discharge cycling (i.e., SOC moves in only one direction or stays flat) over a rolling 8-hour window during operating hours.
**Inputs:** SOC readings
**Intent:** Check that the battery is being charged and discharged throughout the day
**Action:** Check if related to an outage; otherwise ping the DA market team.

#### T3: Curtailment Detection — RT
**Condition:** Variable Energy Resource (VER) forecast significantly exceeds actual generation (VER - Actual > 10 MW or > 20% of VER forecast), indicating the resource is being curtailed.
**Inputs:** VER forecast capacity, actual generation
**Intent:** Check if resources are being curtailed
**Action:** Informational — NA

#### T4: SOC Outside Target Bounds — DA
**Condition:** SOC is above the resource's configured SOC max target or below SOC min target at the end of the DA optimization horizon (i.e., routinely exceeding planned bounds).
**Inputs:** Stora live feeds / SOC readings, per-resource SOC min/max targets
**Intent:** Check if the optimization model is routinely exceeding its own targets
**Action:** Informational — review model parameters

#### T5: Uneconomic PV Curtailment — RT
**Condition:** Resource is being curtailed (VER > actual generation) AND real-time LMP is above the resource's curtailment bid price.
**Inputs:** RT bids, RT market prices, VER capacity, PV generation
**Intent:** Check if curtailment is happening when it shouldn't be (leaving money on the table)
**Action:** Contact DA Org Market Team

#### T6: Invalid Bids — Both (DA & RT)
**Condition:** Any bid submission returns an INVALID status from the market.
**Inputs:** Bid status responses from CAISO
**Intent:** Ensure STORA is creating feasible bids
**Action:** Contact DA Org Market Team

#### T7: RT Bids Not Updated Forward — RT
**Condition:** No RT bid submissions found covering the next 6 hours from current time.
**Inputs:** Bid submission timestamps and target hours
**Intent:** Ensure STORA is continuously updating RT bids on a rolling basis
**Action:** Contact DA Org Market Team

#### T8: Point Data Out of Range — DEFERRED
**Condition:** "Is point data out of allowed range of outcomes"
**Inputs:** "Point data"
**Intent:** See if bad input data is leading to bad optimization outcomes
**Status:** DEFERRED — unclear what "point data" refers to. Open questions:
- Is this SCADA telemetry points (MW, voltage, frequency)?
- Is this forecast input data (price forecasts, load forecasts)?
- Is this bid parameter points (bid curve segments)?
- What are the "allowed ranges" — configured per-resource? Per-data-type?

#### T9: Optimization Quality (Hindsight Analysis) — DEFERRED
**Condition:** "Is STORA optimizing DA products (DA Energy, Capacity) vs RT energy prices with correct assumptions"
**Inputs:** LMP data vs hindsight analysis
**Intent:** Validate that optimization is within respectable results
**Status:** DEFERRED — this is more of a periodic performance scorecard than a real-time alert rule. It requires a hindsight P&L analysis comparing DA bidding decisions against realized RT prices. Recommended to implement as a weekly/monthly analytics report rather than a boolean firing rule. Open questions:
- What threshold of "suboptimal" should trigger a flag?
- What's the benchmark — perfect foresight? Simple heuristic?
- Is this per-hour, per-day, or over a rolling window?

#### T10: Grid Charging Detection — RT
**Condition:** Battery is charging during hours when co-located solar is not producing (night hours or VER = 0), indicating grid charging.
**Inputs:** Charge energy (negative meter MW), VER generation, time of day
**Intent:** Detect grid charging before utility bills or plant operator notices
**Action:** Review whether grid charging was intentional (economic) or erroneous

#### T11: LMP Forecast Accuracy — DA
**Condition:** STORA's DA LMP forecast deviates from actual realized RT LMP by more than a threshold (e.g., MAPE > 50% over a rolling 24-hour window).
**Inputs:** STORA forecast LMPs vs. actual realized RT prices
**Intent:** Monitor whether STORA's price forecasting is accurate enough to make good optimization decisions
**Action:** Informational — review forecast model inputs and parameters

### 15.3 Resource-Specific Rules (RA Compliance)

These rules apply only to specific resources with Resource Adequacy (RA) obligations.

#### R1: Full Capacity Not Offered to Market — DA
**Condition:** The highest MW segment of the DA energy bid in any hour is less than the resource's NQC (Net Qualifying Capacity, approximated by nameplate MW for prototype).
**Inputs:** DA bid segments (highest MW point per hour)
**Intent:** RA bidding rule compliance — RA resources must offer full capacity
**Applies to:** DSFLWR_2_W9CSB2, PUTHCR_1_PCNSB1, KRAMER_1_R1BX3, RSMNDS_2_CSRBT1, SANDRN_2_SS1BT1
**Action:** Informational — NA

#### R2: Full DAME Ancillary Products Not Offered — DA
**Condition:** Resource is not bidding its full capacity into DAME ancillary service products (Imbalance Reserve Up/Down, Reliability Capacity Up/Down — IRU, IRD, RCU, RCD).
**Inputs:** AS bid quantities for IRU, IRD, RCU, RCD products
**Intent:** RA bidding rule compliance — must offer full AS capacity
**Applies to:** DSFLWR_2_W9CSB2, PUTHCR_1_PCNSB1, KRAMER_1_R1BX3, KRAMER_1_R1PX3, RSMNDS_2_CSRBT1, RSMNDS_2_CSRSR1, SANDRN_2_SS1BT1, SANDRN_2_SS1SR1
**Action:** Informational — NA

#### R3: Positive Bid Price Segment (Solar Sign-Flip) — Both
**Condition:** Any bid price segment for a solar/curtailment-priced resource has a positive price. Solar resources should be self-scheduled or curtailment-priced (negative/zero prices only); a positive price indicates a sign error.
**Inputs:** Bid price segments
**Intent:** Catch sign-flip errors on curtailment pricing
**Applies to:** KRAMER_1_R1PX3, RSMNDS_2_CSRSR1, SANDRN_2_SS1SR1
**Action:** Contact DA Org Market Team

### 15.4 Additional Data Requirements

The trader rules require the following data extensions beyond the original prototype schema:

| Data | Description | Used By |
| --- | --- | --- |
| VER forecast (ver_forecast.csv) | Variable Energy Resource capacity forecast per solar resource per interval | T3, T5, T10 |
| LMP forecast (lmp_forecast.csv) | STORA's DA price forecast per node | T11 |
| Bid status field | VALID/INVALID status returned by market | T6 |
| Product field on bids | Energy, IRU, IRD, RCU, RCD | R1, R2 |
| REG award flag | Whether resource has active Regulation award | T1 |
| Per-resource SOC targets | Configured min/max SOC bounds | T4 |
| Per-resource curtailment price | Price threshold for curtailment logic | T5 |

---

## 16. Next Steps (Immediate)

1. Review this document with stakeholders and confirm scope boundaries.
2. Begin Phase 0 discovery (resource inventory, data source documentation).
3. Identify prototype technology choice (Databricks App vs. AI/BI Dashboard).
4. Assign owners to discovery tasks.
5. Schedule kickoff meeting for prototype development (Phase 1).

---

*This is a living document. Version history will be tracked in the workspace.*
