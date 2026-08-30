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

# Running Tests

uv run pytest

# Project Goal

Project Goal

StayOps AI succeeds when a self-managing host can move from scattered property operations to one prioritized view of what needs attention—while the system handles safe analysis autonomously, fails safely when information is missing, and never takes a consequential action without human approval.


### Why I prefer this version

It tells the project story in this order:

**Problem → product → architecture → why multi-agent → real scenario → HITL → failures → LLM decision → evaluation → tech.**


