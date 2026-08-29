# StayOps AI

StayOps AI is a multi-agent operations assistant for a self-managing
short-term-rental host. It coordinates booking, guest communication, turnover,
and maintenance analysis across eight fictional properties and presents one
prioritized Streamlit dashboard.

Routine reads and analysis run automatically. Consequential actions—sending a
message or updating an operational record—require explicit host approval and
are simulated only.

## Current status

StayOps AI V1 is implemented end to end. The current build includes the linked
eight-property dataset, typed read tools, intent and date routing, conditional
parallel specialists, operations synthesis, deterministic safety checks,
LangGraph human review, approval-protected simulated writes, intent-aware
answers, the polished Streamlit command center, and the evaluation harness.

As of August 29, 2026:

- all **207 automated tests pass**;
- all **9 evaluation scenarios pass** and every aggregate target is met;
- routing, specialist activation, priority/risk accuracy, approval enforcement,
  and safe failure handling score `1.0` in the saved deterministic evaluation;
- unsupported critical claims score `0`; and
- external messages and production-system writes remain intentionally disabled.

## System architecture

The application uses LangGraph for orchestration and LangChain runnables with
Pydantic contracts for validated component boundaries.

```text
Host request
    |
Request router
    |
Context loader
    |
    +--> Booking specialist --------+
    +--> Guest specialist ----------+
    +--> Turnover specialist -------+--> Operations synthesizer
    +--> Maintenance specialist ----+             |
                                              Risk/action gate
                                                /          \
                                        Safe response    Human review
                                                           /   |   \
                                                     Approve  Edit  Reject
                                                        |             |
                                                Protected executor    |
                                                        \             /
                                                   Response generator
```

The graph loads only the sources required by the routed intent. Broad briefing
and risk requests run all four specialists concurrently, while domain-specific
requests use the smallest useful specialist set. Every completed path converges
on the response generator so the host-facing narrative reflects the actual
review and execution outcome.

## Synthetic operational data

Six linked JSON fixtures live in `data/`:

- `properties.json`
- `property_rules.json`
- `reservations.json`
- `guest_messages.json`
- `cleaning_schedule.json`
- `maintenance_tickets.json`

The fixtures currently contain 8 properties, 8 property-rule records, 21
reservations, 17 guest messages, 16 cleaning jobs, and 14 maintenance tickets.
Strict Pydantic models validate every record, and every fixture is explicitly
marked as synthetic.

The dashboard resolves calendar language against the current date in
`America/Los_Angeles`, overridable with `STAYOPS_TIMEZONE`. It understands
`today`, `tomorrow`, `yesterday`, day-before/day-after phrases, named weekdays,
`this`/`next`/`last` weekday or weekend scopes, upcoming periods, and explicit
ISO dates or ranges. The daily dashboard automatically refreshes after a local
calendar-day rollover. Tests and evaluation scenarios inject a fixed reference
date to remain deterministic.

The dataset includes same-day turnovers, an unconfirmed cleaner, unanswered
guest messages, guest-impacting and non-blocking maintenance, an early check-in
request, future arrivals, vacant properties, and routine properties that need
no attention.

## Read tools and context loading

The `src/tools/` package exposes six read-only functions:

- `get_properties()`
- `get_property_rules()`
- `get_reservations()`
- `get_guest_messages()`
- `get_cleaning_schedule()`
- `get_maintenance_tickets()`

Each function returns a typed `ReadResult` instead of raising operational data
errors. Tools support property filtering, while dated sources support inclusive
date filtering.

The context loader retries retryable failures once. A persistent failure:

- records a structured workflow error;
- marks `analysis_complete=False`;
- identifies the source in `unavailable_sources`;
- prevents findings from being fabricated from unavailable data; and
- triggers human review when the analysis cannot be considered complete.

`FailureSimulator` provides deterministic first-N-call failures for testing
these recovery paths without randomness.

## Request routing and shared state

`StayOpsState` contains the complete typed workflow state and is initialized by
`create_initial_state()`. The request router extracts:

- operational intent;
- canonical property IDs;
- an ISO date or date range; and
- whether the request could produce a write.

Relative dates use an injectable reference date for deterministic tests. The
state retains loaded context, specialist findings, priorities, proposed
actions, risk decisions, human decisions, write attempts, simulated
executions, errors, run telemetry, and the final response.

## Specialist analysis

Booking, Guest, Turnover, and Maintenance specialists are independent typed
LangChain runnables. They accept only supplied operational records and return
evidence-linked findings with severities, recommended next actions, analyzed
record IDs, confidence, and source-data warnings.

The specialists are read-only:

- **Booking** identifies arrivals, departures, occupancy, booking gaps,
  conflicts, and same-day turnovers.
- **Guest** identifies unanswered messages, complaints, early check-in requests,
  and guest-reported maintenance issues.
- **Turnover** evaluates cleaning schedules, assignments, confirmations, and
  timing against the next arrival. Property-specific cleaner-ready buffers are
  included in the analysis and cited as evidence.
- **Maintenance** evaluates open issues, severity, current guest impact, and
  upcoming reservation impact.

An exception in one specialist branch is isolated so its parallel peers can
still finish. Each branch records status, latency, finding count, warning count,
and analyzed-record count.

## Operations synthesis

After the selected specialists finish, the Operations Synthesizer receives only
their structured findings. It:

- preserves record-level evidence;
- combines explicitly related cross-specialist findings;
- assigns stable priority ranks;
- derives overall operational status;
- identifies affected properties; and
- creates unexecuted action proposals.

Cross-specialist findings are combined only when they share supporting record
evidence. Same-property findings with unrelated evidence remain separate.

## Deterministic risk and action gate

A pure-Python gate evaluates structured findings, typed action proposals, and
the router's write-intent flag. It records explicit reasons for human review
when it detects:

- message sends, reservation modifications, or record updates;
- high- or critical-severity maintenance findings;
- confidence below the configurable `0.75` threshold;
- contradictory turnover findings about the same property and source record;
- required source data that remains unavailable after retry; or
- a request classified as potentially write-producing.

Drafts and read-only review proposals remain safe unless another rule applies.
If gate evaluation fails, the workflow defaults to requiring human review.

## Human review

When review is required, LangGraph `interrupt()` pauses the graph with a
JSON-serializable payload containing proposed actions, evidence-linked
findings, review reasons, and supported Approve, Edit, and Reject decisions.
The current host-facing dashboard intentionally exposes only Approve and Reject;
the programmatic workflow retains Edit-and-reconfirm support.

The graph uses an in-memory checkpointer by default. Callers resume the same
thread with `Command(resume=...)`:

```python
from langgraph.types import Command

config = {"configurable": {"thread_id": "review-123"}}
paused = graph.invoke(initial_state, config=config)
request = paused["__interrupt__"][0].value

completed = graph.invoke(
    Command(
        resume={
            "decision": "approve",
            "action_id": request["proposed_actions"][0]["action_id"],
        }
    ),
    config=config,
)
```

Approve and Reject complete the review. Edit changes only the selected
proposal's description, preserves its type and evidence links, and pauses again
for reconfirmation. Invalid responses remain interrupted with a validation
message. A source-failure review with no proposed action can be acknowledged or
rejected and never reaches a write tool.

## Approval-protected simulated writes

The protected executor supports:

- `send_guest_message()`
- `send_cleaner_message()`
- `update_maintenance_status()`

An approved executable proposal contains its exact tool, target, and
parameters. The workflow then issues a one-time capability bound to the request
ID, action ID, tool, target, content, and complete action fingerprint. Each
write function independently validates and consumes that capability.

Missing, invalid, replayed, cross-tool, cross-request, and content-mismatched
tokens are rejected. Every call produces a structured attempt record;
successful simulations also produce an execution record. Reject creates no
capability or write attempt.

Successful simulations are recorded under `data/runtime/` in separate outbound
message, record-update, and action-history files. Read tools overlay those
records on the immutable fixtures, so the approved result is visible in the UI:
a guest message becomes answered, a cleaner reminder is recorded, or a
maintenance status changes. Runtime files are ignored by Git. The simulation
does not mutate source fixtures or call an external messaging, booking, or
maintenance service.

## Response generation

A typed response generator runs after safe completion, rejection, or approved
execution. It answers the routed question in its first sentence and formats only
the operational fields relevant to the request:

- arrivals include property, guest, check-in time, and guest count;
- daily attention separates Needs Action from Watch items;
- turnover answers include checkout, cleaning target, next check-in,
  confirmation, and next step;
- guest-message answers show urgency, concise content, and approval status;
- maintenance answers show severity, guest impact, status, and next step; and
- property-status answers directly say Ready, At Risk, or Needs Action.

Secondary risks appear separately under `Heads up`. Dates and times are
human-friendly, empty results are stated directly, and approval copy identifies
the exact action waiting for review. The generator reports execution failures
instead of presenting an approval as a successful action.

## Streamlit dashboard

The root `app.py` provides:

- Needs Action, Watch, Ready for Guests, and Arrivals Today portfolio counts;
- prioritized attention cards with supporting evidence;
- property cards and property drill-downs;
- dedicated Guest Messages, Turnovers, Maintenance, and Arrivals workspaces;
- property operating rules;
- URL-backed sidebar navigation that opens the requested workspace;
- Ask StayOps form and quick prompts against the same operations graph;
- an intent-aware `✨ StayOps Answer` shown only after a user asks a question;
- Approve & Send, Approve & Update, Reject, and failure-acknowledgement controls;
  and
- optional Agent Activity details for routing, specialists, synthesis, safety,
  telemetry, and errors.

One controller and checkpointer remain alive within each Streamlit session so
an interrupted review resumes its original graph thread. Approval capability
values are intentionally excluded from the debug display.

When a required source remains unavailable, the dashboard prominently labels
the analysis as incomplete and never presents an unverified property as Ready.

## Current implementation boundaries

The router, specialists, synthesizer, and response generator currently use
deterministic typed LangChain runnables. Their graph boundaries accept injected
runners, allowing structured-output model implementations to be added without
changing the deterministic safety gate or approval controls.

Checkpointing is in memory and supports pause/resume within the running
application. Simulated approved changes persist through the local runtime
overlay, but persistent graph checkpoints, cross-request conversational memory,
and a Mem0 memory layer are not currently configured.

## Installation

This project requires Python 3.12 or newer and uses `uv` for dependency
management.

```bash
uv sync --all-groups
```

## Run the dashboard

```bash
uv run streamlit run app.py
```

## Tests and evaluation

Run the complete automated test suite:

```bash
uv run pytest
```

The current suite contains 207 tests covering datasets, tools, date parsing,
routing, specialist isolation, synthesis, safety, human review, protected
writes, response formatting, evaluation contracts, and Streamlit interactions.

Run the deterministic evaluation harness and refresh its saved reports:

```bash
uv run python -m src.evaluation.runner
```

The evaluation scenarios cover routine operations, same-day turnover, missing
cleaner confirmation, a guest maintenance complaint, conflicting findings,
transient and persistent read failures, an attempted write without approval,
and an explicitly approved write.

Metrics include routing accuracy, specialist activation, priority/risk
accuracy, approval enforcement, safe failure recovery, latency, and unsupported
critical claims. Saved outputs include:

- `evaluation/results/scenario_results.json`
- per-scenario diagnostics under `evaluation/results/scenarios/`
- `evaluation/results/aggregate_report.json`

The latest saved report records 9/9 passing scenarios with
`all_targets_met=true`. The command exits non-zero if an aggregate target is
missed. Automated latency is not a substitute for human usability evidence; use
[`evaluation/usability_protocol.md`](evaluation/usability_protocol.md) to test
whether a host can identify and act on important issues in under five minutes.

## Demo runbook

1. Start the dashboard and ask, “Which guests are arriving today?” for an
   intent-aware arrivals answer. Try “tomorrow,” a weekday name, or “this
   weekend” to demonstrate calendar routing.
2. Inspect a proposed cleaner or maintenance action in Human Approvals, then
   Approve or Reject it. An approval updates the local simulated runtime and the
   corresponding UI records without contacting anyone.
3. Enable Agent Activity to inspect routing, selected specialists, synthesis,
   safety checks, latency, and structured errors.
4. Run `uv run python -m src.evaluation.runner` and inspect
   `evaluation/results/scenarios/persistent_tool_failure.json` for the
   two-attempt failure, incomplete-analysis escalation, review pause, and zero
   executions.
