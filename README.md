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

Install and validate with:

```bash
uv sync --all-groups
uv run pytest
```
