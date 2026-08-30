# StayOps AI 🏡
### Multi-Agent Operations Manager for Short-Term Rental Hosts

> **8 properties. One operations command center. Know what's ready, what's at risk, and what needs your approval.**

StayOps AI is a multi-agent operations system built for a self-managing short-term rental host managing eight properties.

Instead of manually checking reservations, guest messages, cleaning schedules, and maintenance issues across multiple properties, StayOps coordinates specialized agents to answer a much simpler question:

> **What needs my attention right now?**

The system autonomously reads operational data, routes work to specialized agents, combines their findings into a prioritized briefing, and pauses for human approval before any consequential action is taken.

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

# Project Structure

```text
stayops-ai/
│
├── app.py
├── pyproject.toml
├── README.md
├── .env.example
│
├── data/
│
├── src/
│   ├── agents/
│   ├── config/
│   ├── evaluation/
│   ├── graph/
│   ├── llm/
│   ├── models/
│   ├── safety/
│   ├── tools/
│   └── ui/
│
├── evaluation/
└── tests/
```

---

# Architecture

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
             ┌────────────┼────────────┐
             │            │            │
             ▼            ▼            ▼
          BOOKING       GUEST       TURNOVER
           AGENT        AGENT         AGENT
             │            │            │
             └────────────┼────────────┐
                          │            │
                          ▼            ▼
                    MAINTENANCE AGENT
                          │
                          ▼
                OPERATIONS SYNTHESIZER
                   Deterministic / LLM
                          │
                          ▼
                 DETERMINISTIC SAFETY
                    /             \
                   /               \
             READ ONLY          ACTION
                 │                 │
                 ▼                 ▼
              RESPONSE       HUMAN REVIEW
                                  │
                           Approve/Edit/Reject
                                  │
                                  ▼
                         PROTECTED WRITE TOOL
                                  │
                                  ▼
                               RESPONSE

```
<img width="1536" height="1024" alt="ChatGPT Image Aug 28, 2026, 09_47_01 PM" src="https://github.com/user-attachments/assets/b4d64be6-45f5-469b-abf1-6fcad5c46a6e" />

---

# Failure Handling

A multi-agent system should not work only on the happy path.
StayOps read tools support controlled failure simulation.

```text
Tool Call
    │
    ▼
 Success?
  /      \
Yes       No
 │         │
Continue  Retry once
            │
            ▼
         Success?
         /     \
       Yes      No
        │        │
    Continue   Record error
                 │
                 ▼
          Can analysis continue?
             /          \
           Yes           No
            │             │
      Partial result   Human review

```

---

# Tech Stack

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
| Persistence        | LangGraph checkpointer |

---

# Running Locally

uv sync

# Run StayOps with deterministic synthesis

SYNTHESIZER_MODE=deterministic uv run streamlit run app.py

# Run with Ollama

Make sure Ollama is running and the configured model is available.

SYNTHESIZER_MODE=llm
LLM_PROVIDER=ollama
LLM_MODEL=<your-model>

uv run streamlit run app.py

# Run with Nebius

Configure the required environment variables:

SYNTHESIZER_MODE=llm
LLM_PROVIDER=nebius
LLM_MODEL=<your-model>
LLM_API_KEY=<your-key>
LLM_BASE_URL=<configured-nebius-endpoint>

uv run streamlit run app.py

Never commit API keys to the repository.

# LLM Synthesizer Comparison

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

# Running Tests

uv run pytest

# Project Goal

Project Goal

StayOps AI succeeds when a self-managing host can move from scattered property operations to one prioritized view of what needs attention—while the system handles safe analysis autonomously, fails safely when information is missing, and never takes a consequential action without human approval.


### Why I prefer this version

It tells the project story in this order:

**Problem → product → architecture → why multi-agent → real scenario → HITL → failures → LLM decision → evaluation → tech.**
