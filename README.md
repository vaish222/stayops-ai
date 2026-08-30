# StayOps AI 🏡
### Multi-Agent Operations Manager for Short-Term Rental Hosts

> **8 properties. One operations command center. Know what's ready, what's at risk, and what needs your approval.**

StayOps AI is a multi-agent operations system built for a self-managing short-term rental host managing eight properties.

Instead of manually checking reservations, guest messages, cleaning schedules, and maintenance issues across multiple properties, StayOps coordinates specialized agents to answer a much simpler question:

> **What needs my attention right now?**

The system autonomously reads operational data, routes work to specialized agents, combines their findings into a prioritized briefing, and pauses for human approval before any consequential action is taken.

> **Simulation boundary:** StayOps does not send real guest or cleaner messages and does not update an external property-management system. Approved actions are simulated, saved to the local `data/runtime/` overlay, and reflected in the UI without changing the source JSON fixtures.

---

## Why I Built This

Managing multiple short-term rentals is not just a data lookup problem.

A host may need to simultaneously understand:

- Who is checking in or out today?
- Is each property ready for the next guest?
- Has the cleaner confirmed?
- Is a guest waiting for a response?
- Could an open maintenance issue affect an upcoming stay?
- Which issue should be handled first?
- Which properties require no action?

The information may already exist, but the host still has to connect the dots.

StayOps AI turns those scattered operational signals into:

**Read → Analyze → Prioritize → Escalate → Human Approve → Act**

---

## What StayOps Can Do

StayOps currently manages four operational areas across eight synthetic properties:

### 📅 Booking Operations
- Today's arrivals and departures
- Upcoming reservations
- Same-day turnovers
- Occupancy and booking conflicts

### 💬 Guest Operations
- Unanswered messages
- Guest requests
- Complaints
- Maintenance reports
- Communication urgency

### 🧹 Turnover Operations
- Cleaner assignments
- Cleaning confirmation
- Checkout → cleaning → next check-in timing
- Turnover readiness risk

### 🔧 Maintenance Operations
- Open maintenance tickets
- Severity
- Current guest impact
- Upcoming reservation impact

---

## Project Structure

```text
stayops-ai/
│
├── app.py
├── architecture.md
├── pyproject.toml
├── product_requirements.md
├── README.md
├── .env.example
│
├── data/
│   └── runtime/
│
├── src/
│   ├── agents/
│   ├── evaluation/
│   ├── graph/
│   ├── llm/
│   ├── models/
│   ├── safety/
│   ├── time_context.py
│   ├── tools/
│   └── ui/
│
├── evaluation/
└── tests/
```

---

## Architecture

StayOps is built as a stateful LangGraph workflow rather than a single LLM call.

```text
                              HOST
                               │
                               ▼
                        STREAMLIT UI
                               │
                               ▼
                     DETERMINISTIC ROUTER
                               │
                               ▼
                         CONTEXT LOADER
                               │
                    SELECT SPECIALISTS BY INTENT
                               │
            ┌──────────┬────────┴───────┬────────────┐
            │          │                │            │
            ▼          ▼                ▼            ▼
         BOOKING     GUEST           TURNOVER    MAINTENANCE
          AGENT      AGENT             AGENT        AGENT
            │          │                │            │
            └──────────┴────────┬───────┴────────────┘
                               │
                   (parallel selected specialists)
                               │
                               ▼
                     OPERATIONS SYNTHESIZER
                        Deterministic / LLM
                               │
                               ▼
                  DETERMINISTIC RISK/ACTION GATE
                         /                 \
                        /                   \
              NO REVIEW REQUIRED       REVIEW REQUIRED
                       │                       │
                       │                       ▼
                       │                 HUMAN REVIEW
                       │              Approve or Reject
                       │                /            \
                       │               /              \
                       │      APPROVAL-PROTECTED     RECORD
                       │       SIMULATED WRITE      REJECTION
                       │               \              /
                       │                \            /
                       │          MORE ACTIONS TO REVIEW?
                       │             Yes: review again
                       │             No: continue
                       │                       │
                       └───────────────────────┘
                                               │
                                               ▼
                              INTENT-AWARE RESPONSE GENERATOR

```

The four specialist nodes fan out from the context loader and run in parallel when selected; maintenance is not downstream of the other specialists. The Streamlit approval UI currently exposes per-action **Approve** and **Reject** controls. The backend human-review contract also supports **Edit → Reconfirm** for programmatic callers, but that control is not exposed in the current UI.

Every approved write receives a one-time capability bound to the exact request, action, parameters, and write tool. Reusing the capability or changing the reviewed action causes the simulated write to be rejected.
<img width="1536" height="1024" alt="ChatGPT Image Aug 28, 2026, 09_47_01 PM" src="https://github.com/user-attachments/assets/b4d64be6-45f5-469b-abf1-6fcad5c46a6e" />

---

## Failure Handling

A multi-agent system should not work only on the happy path.
StayOps read tools support controlled failure simulation.

```text
Read Tool Call
      │
      ▼
   Success?
   /      \
 Yes       No
  │         │
Continue    ▼
       Retryable with an attempt remaining?
             /                    \
           Yes                     No
            │                       │
       Retry once                   │
         /     \                    │
    Success   Failure               │
       │         │                  │
   Continue     └──────────────────┘
                         │
                         ▼
          Record structured error and
             mark source unavailable
                         │
                         ▼
          Produce partial/incomplete analysis
                         │
                         ▼
              Deterministic safety gate
                         │
                         ▼
            Human review / acknowledgement

```

Unavailable source data is never treated as an all-clear. Persistent read failures and synthesis failures remain visible in graph state and require human review or acknowledgement before the workflow completes.

---

## Tech Stack

| Layer              | Technology             |
| ------------------ | ---------------------- |
| Language           | Python                 |
| Agent Framework    | LangChain              |
| Orchestration      | LangGraph              |
| Validation         | Pydantic               |
| Hosted LLM         | Nebius                 |
| Local LLM          | Ollama                 |
| UI                 | Streamlit              |
| Package Management | uv                     |
| Testing            | pytest                 |
| Data               | Synthetic JSON         |
| Workflow checkpointing | In-memory LangGraph checkpointer |
| Simulated write persistence | Local JSON overlay in `data/runtime/` |

---

## Running Locally

### Prerequisites

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Ollama running locally only when using the Ollama provider

Install the project dependencies:

```bash
uv sync
```

StayOps uses deterministic synthesis by default, so no LLM credentials are required for the standard local run:

### Run StayOps with deterministic synthesis

```bash
uv run streamlit run app.py
```

The operating timezone is controlled by `STAYOPS_TIMEZONE` and defaults to `America/Los_Angeles`. Override it when needed:

```bash
STAYOPS_TIMEZONE=America/New_York uv run streamlit run app.py
```

### Load configuration from `.env`

The application does not automatically load `.env`. Export its values into the shell before starting StayOps:

```bash
set -a
source .env
set +a
uv run streamlit run app.py
```

### Run with Ollama

Make sure Ollama is running and the configured model is available.

```bash
SYNTHESIZER_MODE=llm \
LLM_PROVIDER=ollama \
LLM_MODEL=mistral:latest \
OLLAMA_BASE_URL=http://localhost:11434 \
uv run streamlit run app.py
```

### Run with Nebius

`NEBIUS_API_KEY` is the preferred credential name for Nebius. `LLM_API_KEY` remains supported as a compatibility fallback.

```bash
SYNTHESIZER_MODE=llm \
LLM_PROVIDER=nebius \
LLM_MODEL=Qwen/Qwen3-235B-A22B-Instruct-2507 \
NEBIUS_API_KEY="replace-with-nebius-api-key" \
LLM_BASE_URL=https://api.tokenfactory.nebius.com/v1/ \
uv run streamlit run app.py
```

Never commit API keys to the repository.

## LLM Synthesizer Comparison

StayOps was evaluated with deterministic synthesis, local Ollama synthesis,
and hosted Nebius synthesis. Each option ran the same nine controlled scenarios
five times. Eight scenarios invoke the synthesizer, producing 40 synthesis runs
per option.

| Synthesizer | Model | Native completion | Fallback rate | Grounding failure rate | Average synthesis latency | p95 synthesis latency |
| ----------- | ----- | ----------------: | ------------: | ---------------------: | ------------------------: | --------------------: |
| Deterministic | N/A | 100% | 0% | 0% | 0.12 ms | 0.16 ms |
| Nebius | `Qwen/Qwen3-235B-A22B-Instruct-2507` | 62.5% | 37.5% | 37.5% | 2.67 s | 5.51 s |
| Ollama | `mistral:latest` | 37.5% | 62.5% | 62.5% | 5.76 s | 13.04 s |

All three options recorded a 100% scenario pass rate because the configured
deterministic fallback safely completed workflows when an LLM response failed
strict grounding validation. For that reason, native completion and fallback
rates are more useful than the overall pass rate when comparing providers.

For the currently tested models, deterministic synthesis is the recommended
default. Nebius is the stronger LLM candidate, but its grounding failures need
to be reduced before relying on it without fallback. The tested Ollama model
was slower and required fallback more often. These latency measurements reflect
the machine and network used for this benchmark and should not be treated as
universal provider performance.

The complete report is available at
[`evaluation/results/provider_comparison/comparison_report.json`](evaluation/results/provider_comparison/comparison_report.json).
Reproduce the comparison with:

```bash
set -a
source .env
set +a
uv run python -m src.evaluation.provider_comparison --runs 5
```

## Running Tests

uv run pytest

## Project Goal

StayOps AI succeeds when a self-managing host can move from scattered property operations to one prioritized view of what needs attention—while the system handles safe analysis autonomously, fails safely when information is missing, and never takes a consequential action without human approval.
