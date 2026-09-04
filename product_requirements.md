StayOps AI

Product Requirements Document

Multi-Agent Short-Term Rental Operations Manager

Version 1.0 \| Python 3.12 \| LangChain + LangGraph \| Streamlit \| 8
synthetic properties \| Pydantic \| uv

# 1. Product Vision

Managing eight short-term rental properties means constantly switching
between reservations, arrivals, departures, cleaners, guest messages,
maintenance issues, and operational follow-ups. StayOps AI coordinates
specialized agents across all eight properties and turns scattered
operational information into a prioritized action plan.

The desired experience is: "StayOps already checked. Here are the three
things that need me."

# 2. One-Liner

StayOps AI helps a self-managing short-term-rental host operate eight
properties from one Streamlit dashboard, replacing the daily manual work
of checking reservations, guest messages, cleaning schedules, and
maintenance issues across multiple places. It autonomously coordinates
specialized booking, guest communication, turnover, and maintenance
agents using operational tools, prioritizes what needs attention across
all properties, and hands off to the host before any message is sent,
reservation is modified, or other write action is taken. Success means
the host can identify and act on the day's important property issues in
under five minutes, with at least 90% of test scenarios correctly routed
and prioritized.

# 3. Problem Statement

The problem is not simply retrieving facts. The harder problem is
combining information across operational areas, determining what
matters, and deciding what should happen next. StayOps AI is therefore a
multi-agent coordination system rather than a simple chatbot.

# 4. Target User

A self-managing host operating approximately eight short-term rental
properties without a full-time property-management team. Core need: one
place to understand what needs attention without checking every system
manually.

# 5. Eight Synthetic Properties

-   Lake House

-   Pine House

-   City Loft

-   Garden Cottage

-   Sunset House

-   Beach Bungalow

-   Mountain Retreat

-   Downtown Suite

No real guest information should be used in the public repository.

# 6. V1 Scope

-   Booking: arrivals, departures, occupancy, same-day turnovers,
    reservation conflicts, booking gaps.

-   Guest: unanswered messages, special requests, complaints,
    maintenance reports, urgent issues.

-   Turnover: cleaner assignment, cleaning confirmation, checkout, next
    check-in, readiness risk.

-   Maintenance: open tickets, severity, guest impact, upcoming
    reservation impact, unresolved issues.

# 7. Core User Experiences

-   What needs my attention today?

-   Which properties have guests arriving today?

-   Are all properties ready for today's check-ins?

-   Which cleaners haven't confirmed?

-   Are there unresolved guest issues?

-   Which maintenance issues could affect upcoming stays?

-   What's the highest-risk property today?

-   Handle the cleaning issue at Lake House.

Any request that can cause a write action must route through human
approval.

# 8. Multi-Agent Architecture

Figure 1. StayOps AI hand-drawn whiteboard-style architecture.

# 9. LangGraph State

    class StayOpsState(TypedDict):
        request_id: str
        host_query: str
        intent: str
        property_scope: list[str]
        date_scope: str | None
        write_requested: bool
        property_context: dict
        reservation_context: dict
        booking_findings: list
        guest_findings: list
        turnover_findings: list
        maintenance_findings: list
        operational_findings: list
        priority_items: list
        proposed_actions: list
        requires_human_review: bool
        human_decision: dict | None
        executed_actions: list
        errors: list
        final_response: str

Checkpoint state so workflows can pause during human approval and resume
later.

# 10. Synthetic Data

    data/
    ├── properties.json
    ├── reservations.json
    ├── guest_messages.json
    ├── cleaning_schedule.json
    ├── maintenance_tickets.json
    └── property_rules.json

-   Lake House: checkout 11 AM, next guest 4 PM, cleaner confirmation
    missing.

-   Pine House: current guest reports AC failure; next reservation
    tomorrow.

-   City Loft: guest arriving 3 PM; cleaning confirmed.

-   Beach Bungalow: guest requested early check-in.

-   Mountain Retreat: open plumbing ticket; no guest currently staying.

# 11. Agent Responsibilities

## Request Router

Extract intent, property scope, date range, and read vs. write intent.

## Booking Agent

Analyze arrivals, departures, occupancy, same-day turnovers, conflicts,
and gaps.

## Guest Agent

Analyze unanswered messages, requests, complaints, urgency, and
maintenance reports. May draft but never send.

## Turnover Agent

Analyze checkout, cleaner assignment, confirmation, next check-in, and
readiness risk.

## Maintenance Agent

Analyze issue severity, guest impact, operational impact, and upcoming
reservation impact.

## Operations Synthesizer

Combine structured specialist findings into a prioritized briefing and
proposed next actions.

# 12. Deterministic Risk / Action Gate

    send_message -> HUMAN APPROVAL
    modify_reservation -> HUMAN APPROVAL
    update_record -> HUMAN APPROVAL
    HIGH maintenance severity -> OPERATIONAL WARNING
    low confidence -> OPERATIONAL WARNING
    conflicting specialist findings -> OPERATIONAL WARNING
    unavailable source or synthesis -> OPERATIONAL WARNING

Hard safety and approval rules should use deterministic Python rather
than an LLM.

# 13. Human-in-the-Loop

    Lake House needs attention
    Checkout: 11:00 AM
    Next guest: 4:00 PM
    Cleaner confirmation: Missing

    Proposed action:
    "Hi Alex, can you confirm Lake House will be cleaned and ready by 2 PM?"

    [ APPROVE ]  [ EDIT ]  [ REJECT ]

-   Approve executes the simulated action.

-   Edit lets the host modify and reconfirm.

-   Reject records the rejection and performs no action.

# 14. Tools

-   Read: get_properties(), get_reservations(), get_guest_messages(),
    get_cleaning_schedule(), get_maintenance_tickets().

-   Write - approval required: send_guest_message(),
    send_cleaner_message(), update_maintenance_status().

# 15. Failure Handling

Every read tool can simulate failure. Retry once; if data is still
missing or contradictory, record the error and either return a partial
result with a warning or escalate to the host. Never fabricate missing
operational information.

# 16. Streamlit Dashboard

    STAYOPS AI
    Your 8 properties. One clear view.

    2 Need Attention | 2 Watch | 4 Ready

    NEEDS ATTENTION
    Lake House - Cleaning confirmation missing; guest arrives 4 PM
    Pine House - AC issue reported; guest currently staying

    ASK STAYOPS
    "What needs my attention today?"

# 17. Project Structure

    stayops-ai/
    ├── app.py
    ├── pyproject.toml
    ├── README.md
    ├── .env.example
    ├── data/
    ├── src/
    │   ├── config/
    │   ├── models/
    │   ├── tools/
    │   ├── agents/
    │   ├── graph/
    │   ├── safety/
    │   └── evaluation/
    ├── evaluation/
    └── tests/

# 18. Development Phases + Codex Prompts

## Phase 0 - Synthetic Operations Dataset

Build Phase 0 of my Python project StayOps AI, a multi-agent short-term
rental operations manager. Create realistic synthetic JSON datasets for
eight fictional properties: Lake House, Pine House, City Loft, Garden
Cottage, Sunset House, Beach Bungalow, Mountain Retreat, and Downtown
Suite. Create properties.json, reservations.json, guest_messages.json,
cleaning_schedule.json, maintenance_tickets.json, and
property_rules.json. Include same-day turnovers, missing cleaner
confirmations, unanswered guest messages, maintenance issues, early
check-in requests, upcoming arrivals, vacant properties, and properties
requiring no attention. Ensure IDs link correctly across files. Use
fictional identities only. Add Pydantic models and validation tests. Do
not build agents or LangGraph yet.

## Phase 1 - Tools

Build Phase 1 of StayOps AI. Create modular Python read tools:
get_properties, get_reservations, get_guest_messages,
get_cleaning_schedule, and get_maintenance_tickets. Support
property/date filtering, typed results, and structured errors. Add
configurable simulated tool failures for retry/recovery testing. Do not
implement agents yet.

## Phase 2 - State + Request Router

Build Phase 2 using LangGraph. Create typed StayOpsState for request
information, scope, specialist findings, proposed actions, approval
state, executed actions, errors, and final response. Create a Pydantic
Request Router that converts host queries into intent, property scope,
date scope, and write_requested. Test read and write examples. Do not
build specialists yet.

## Phase 3 - Four Specialist Agents

Build Booking, Guest, Turnover, and Maintenance agents using LangChain
and Pydantic structured output. Each agent must use only supplied
tools/data, return structured findings, avoid unsupported assumptions,
and never perform write actions. Keep every agent independently
testable.

## Phase 4 - Parallel LangGraph

After routing and context loading, run the four specialists in parallel
where appropriate and merge their outputs safely into StayOpsState.
Isolate failures, and log which agents ran, latency, and errors. Do not
add HITL yet.

## Phase 5 - Operations Synthesizer

Add an Operations Synthesizer that receives only structured specialist
findings and produces overall status, prioritized findings, affected
property, severity, evidence, recommended next action, and whether an
action is proposed. Do not add unsupported facts or execute actions.
Test cross-agent reasoning such as same-day arrival plus missing cleaner
confirmation.

## Phase 6 - Risk / Action Gate

Add a deterministic Python gate. Human approval is required only when
the host explicitly requests a message send, reservation modification,
or record update. High-severity maintenance, low confidence,
conflicting findings, and incomplete source or synthesis results remain
visible as non-blocking operational warnings. Do not use an LLM. Return
requires_human_review, explicit approval reasons, and operational
warnings. Unit-test every rule.

## Phase 7 - Human-in-the-Loop

Add LangGraph human-in-the-loop behavior. When requires_human_review is
true, pause using interrupt(). Present proposed action plus evidence.
Support Approve, Edit, and Reject. Resume the same checkpointed thread
with Command(resume=...). No write tool may execute without explicit
approval.

## Phase 8 - Approval-Protected Write Tools

Implement simulated send_guest_message, send_cleaner_message, and
update_maintenance_status tools. Require an approved action token/state
before execution. Log all attempted and executed actions. Reject
unapproved writes and add tests proving the safety boundary.

## Phase 9 - Streamlit UI

Build a Streamlit dashboard for eight properties. Show counts for Need
Attention, Watch, and Ready; prioritized issues; property drill-down;
Ask StayOps input; specialist findings in debug mode; and
Approve/Edit/Reject controls for interrupted actions. Keep the UI
connected to the same LangGraph backend.

## Phase 10 - Failure Recovery + Evaluation

Create controlled evaluation scenarios for routine operations, same-day
turnover, missing cleaner confirmation, guest maintenance complaint,
conflicting findings, tool failure, and attempted writes without
approval. Measure routing accuracy, correct specialist activation,
priority/risk accuracy, approval enforcement, safe failure handling,
latency, and unsupported critical claims. Save scenario-level results
and an aggregate report.

# 19. Evaluation Targets

-   Routing accuracy \>= 90%.

-   Correct specialist activation \>= 90%.

-   Priority/risk classification \>= 90%.

-   Write-action approval enforcement = 100%.

-   Safe handling of simulated tool failures = 100%.

-   Unsupported critical operational claims = 0.

-   Host can identify and act on important issues in under 5 minutes.

# 20. Definition of Done

-   Eight synthetic properties and linked operational datasets exist.

-   Four specialist agents return structured outputs.

-   Parallel fan-out/fan-in works.

-   Operations Synthesizer produces prioritized findings.

-   Deterministic risk/action gate works.

-   HITL pause/resume works for Approve/Edit/Reject.

-   At least one simulated write action is approval-protected.

-   Tool retry and safe escalation are tested.

-   Streamlit shows daily briefing and issue drill-down.

-   Evaluation scenarios and aggregate metrics are available.

-   Demo includes happy path, risky issue, human approval, and tool
    failure.

# 21. Future Enhancements

-   Voice Operations Assistant as another interface to the same
    orchestrator.

-   Real guest/cleaner messaging integrations.

-   Calendar synchronization and automated turnover scheduling.

-   Pricing/revenue recommendation agent with approval before changes.

-   Long-term operational memory and trend analysis.

-   Vendor and inventory agents.

-   Real short-term-rental platform integrations only after a safe
    sandboxed version is proven.
