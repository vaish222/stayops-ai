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

Install and validate with:

```bash
uv sync --all-groups
uv run pytest
```
