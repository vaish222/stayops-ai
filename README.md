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

Install and validate with:

```bash
uv sync --all-groups
uv run pytest
```
