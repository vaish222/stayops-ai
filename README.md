# StayOps AI

StayOps AI is a multi-agent operations assistant for a self-managing
short-term-rental host. It coordinates booking, guest communication, turnover,
and maintenance analysis across eight fictional properties and presents one
prioritized Streamlit dashboard.

Routine reads and analysis run automatically. Consequential actions—sending a
message or updating an operational record—require explicit host approval and
are simulated only.

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

Strict Pydantic models validate every record, and every fixture is explicitly
marked as synthetic. The dashboard resolves relative calendar language against
the current date in `America/Los_Angeles` (overridable with
`STAYOPS_TIMEZONE`). Tests and evaluation scenarios inject a fixed reference
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
findings, review reasons, and Approve, Edit, and Reject options.

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

These functions do not mutate the JSON fixtures or call external services.

## Response generation

A typed response generator runs after safe completion, rejection, or approved
execution. It combines the evidence-grounded operations briefing with the
actual workflow outcome. It also reports execution failures instead of
presenting an approval as a successful action.

## Streamlit dashboard

The root `app.py` provides:

- Need attention, Watch, and Ready portfolio counts;
- ranked priorities with supporting evidence;
- property cards and property drill-downs;
- Messages, Cleanings, Maintenance, and Upcoming arrivals workspaces;
- property operating rules;
- Ask StayOps queries against the same operations graph;
- Approve, Edit and reconfirm, Reject, and acknowledgement controls; and
- an optional debug view for specialist findings, run telemetry, and errors.

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
application. Persistent checkpoint storage, cross-request operational memory,
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

The command exits non-zero if an aggregate target is missed. Automated latency
is not a substitute for human usability evidence; use
[`evaluation/usability_protocol.md`](evaluation/usability_protocol.md) to test
whether a host can identify and act on important issues in under five minutes.

## Demo runbook

1. Start the dashboard and ask, “Which guests are arriving at City Loft today?”
   for the happy path.
2. Return to the daily briefing, inspect the Lake House cleaner issue and its
   evidence, then Approve, Edit, or Reject the proposed simulated action.
3. Run `uv run python -m src.evaluation.runner` and inspect
   `evaluation/results/scenarios/persistent_tool_failure.json` for the
   two-attempt failure, incomplete-analysis escalation, review pause, and zero
   executions.
