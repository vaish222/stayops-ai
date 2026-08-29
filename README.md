# StayOps AI

StayOps AI helps a self-managing short-term-rental host operate eight
fictional properties from one dashboard. It is being built phase by phase from
the requirements in `product_requirements.md`.

## Phase 0: synthetic operations dataset

Phase 0 provides six linked JSON fixtures in `data/` and strict Pydantic domain
models in `src/models/`. Every record is explicitly marked as synthetic. The
fixtures use **2026-08-28** as their fixed operating date so scenarios and
future evaluations remain deterministic.

The data includes same-day turnovers, an unconfirmed cleaner, unanswered guest
messages, guest-impacting and non-blocking maintenance, an early check-in
request, future arrivals, vacant properties, and routine properties that need
no attention.

## Phase 1: read tools

The `src/tools/` package exposes five read-only functions:

- `get_properties()`
- `get_reservations()`
- `get_guest_messages()`
- `get_cleaning_schedule()`
- `get_maintenance_tickets()`

Each function returns a typed `ReadResult` instead of throwing operational data
errors. Tools support property filtering, and dated records support inclusive
date filtering. `FailureSimulator` can deterministically fail the first N calls
to any tool so retry and recovery behavior can be tested without randomness.

## Phase 2: state and request routing

`StayOpsState` defines the complete typed workflow state and is initialized by
`create_initial_state()`. The Pydantic request router extracts an operational
intent, canonical property IDs, an ISO date or date range, and whether the host
is asking for a write action. Relative dates use an injectable reference date
for deterministic tests.

The current LangGraph is intentionally limited to:

```text
START -> request_router -> END
```

No specialist agents or operational synthesis run in Phase 2.

## Phase 3: specialist agents

Booking, Guest, Turnover, and Maintenance specialists are independent
LangChain runnables with Pydantic input and output schemas. They accept only
supplied operational records and return evidence-linked findings, severities,
recommended next actions, analyzed record IDs, and source-data warnings.

The specialists are read-only analyzers: they cannot send messages, modify
reservations, update tickets, or execute any other operational action. They are
not connected to the LangGraph workflow until the parallel orchestration phase.

## Phase 4: parallel LangGraph workflow

The Phase 4 graph routes each request, loads only the required read context,
and conditionally fans out to the relevant specialists. Broad briefing and risk
queries run all four specialists concurrently; domain queries run the smallest
useful specialist set.

Retryable read failures are retried once. Persistent source failures become
structured workflow errors without fabricated findings, while an exception in
one specialist branch is caught so its parallel peers can still complete. Each
run records the agents selected, status, latency, finding count, warning count,
and analyzed-record count. Specialist outputs merge into their dedicated
`StayOpsState` fields. Synthesis and human review are not part of this phase.

## Phase 5: operations synthesis

After all selected specialist branches finish, one deferred Operations
Synthesizer receives only their structured findings. It preserves source
evidence, combines explicitly related cross-agent findings, assigns stable
priority ranks, derives an overall status, identifies affected properties, and
records recommended actions as unexecuted proposals.

The cross-agent combination requires shared record evidence. For example, Lake
House's same-day booking turnover and missing cleaner confirmation combine
because both cite the same reservations. Same-property findings with unrelated
evidence remain separate. Risk gating, approval, and action execution are not
implemented in Phase 5.

## Phase 6: deterministic risk and action gate

After synthesis, a pure-Python gate evaluates only structured findings, typed
action proposals, and the router's write-intent flag. It sets
`requires_human_review` and records explicit, evidence-linked reasons for:

- message sends, reservation modifications, and record updates;
- high- or critical-severity maintenance findings;
- confidence below the configurable `0.75` default threshold;
- contradictory turnover findings about the same property and source record;
- any request the router classifies as potentially write-producing.

Drafts and read-only review proposals remain safe unless another rule applies.
If gate evaluation fails, the workflow defaults to requiring review. Phase 6
stops after this decision: it does not pause for a person or execute any action.

## Phase 7: checkpointed human review

`build_phase_7_graph()` adds a LangGraph `interrupt()` only when the Phase 6
gate requires review. The JSON-serializable interrupt payload contains the
proposed actions, prioritized findings with evidence, explicit review reasons,
and the available Approve, Edit, and Reject decisions.

The graph uses an in-memory checkpointer by default. Callers provide a stable
thread ID and resume that same thread with `Command(resume=...)`:

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

Approve and Reject complete the review. Edit can change only a selected
proposal's description, preserves its type and evidence links, and pauses again
for reconfirmation. Invalid responses remain interrupted with a validation
message. Phase 7 records decisions but contains no write tools or action
execution nodes; those remain reserved for Phase 8.

## Phase 8: approval-protected simulated writes

`build_phase_8_graph()` extends the checkpointed review workflow with three
simulated write tools:

- `send_guest_message()` replies to an evidence-linked guest message;
- `send_cleaner_message()` contacts the cleaner for an evidence-linked job;
- `update_maintenance_status()` records the exact reviewed status change.

Each executable proposal includes its tool, target record, and exact parameters
in the human-review payload. After an Approve decision, the workflow issues a
one-time capability bound to the request ID, action ID, tool, target, content,
and complete action fingerprint. Each tool independently validates and consumes
that capability. Missing, invalid, replayed, cross-tool, cross-request, or
content-mismatched tokens are rejected.

Every tool call returns a structured attempt record, including rejected calls.
The graph stores these in `action_attempts`, stores successful simulations in
`executed_actions`, and retains issued capabilities in `approval_grants` for
auditability. Reject creates no capability or write attempt. Edit updates the
displayed proposal and executable message together, then requires
reconfirmation before a new capability can be issued.

These tools are simulations only and do not mutate the JSON fixtures or call an
external service. Phase 8 does not add a dashboard or any Phase 9 behavior.

Install and validate with:

```bash
uv sync --all-groups
uv run pytest
```
