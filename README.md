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
│   ├── observability/
│   ├── safety/
│   ├── time_context.py
│   ├── tools/
│   ├── ui/
│   └── voice/
│
├── evaluation/
│   └── week4/
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

The request router also derives a deterministic normalized operation. That
sub-intent selects the smallest useful specialist set: booking lookups use
Booking, cleaner status uses Turnover, timing uses Booking + Turnover, property
readiness uses Booking + Turnover + Maintenance, and broad briefings use all
four. Selected specialists fan out from the context loader and run in parallel;
maintenance is not downstream of another specialist.

Read-only recommendations remain autonomous. Only explicit write intent opens
the Streamlit approval UI, which exposes per-action **Approve** and **Reject**
controls. The backend human-review contract also supports **Edit → Reconfirm**
for programmatic callers, but that control is not exposed in the current UI.

Every approved write receives a one-time capability bound to the exact request, action, parameters, and write tool. Reusing the capability or changing the reviewed action causes the simulated write to be rejected.

The optional ElevenLabs voice interface wraps **Ask StayOps** only: recorded audio is transcribed, confirmed by the user, and submitted through the same request router. Spoken answers are generated on demand. Voice is not connected to the human-review resume path, so approvals and rejections remain on-screen only.
<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/360033b1-3d99-4d03-8a05-d37eaf79d934" />



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
             Non-blocking warning in answer

```

Unavailable source data is never treated as an all-clear. Persistent read
failures, synthesis failures, low confidence, conflicts, and severe maintenance
remain visible as operational warnings without opening write approval. Explicit
write requests still require human approval, and the protected tools continue to
reject any execution without a valid one-time approval capability.

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
| Voice interface    | ElevenLabs (optional)  |
| Observability      | LangSmith (optional)   |
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

### Enable ElevenLabs voice for Ask StayOps

Voice is disabled by default. Add a restricted ElevenLabs key and a voice ID to `.env` to enable push-to-talk questions and on-demand spoken answers:

```bash
VOICE_ENABLED=true
ELEVENLABS_API_KEY="replace-with-restricted-elevenlabs-key"
ELEVENLABS_STT_MODEL=scribe_v2
ELEVENLABS_TTS_MODEL=eleven_flash_v2_5
ELEVENLABS_VOICE_ID="replace-with-elevenlabs-voice-id"
ELEVENLABS_OUTPUT_FORMAT=mp3_44100_128
ELEVENLABS_LANGUAGE_CODE=eng
VOICE_MAX_SECONDS=30
```

Export `.env` before starting Streamlit as shown above. Voice is available only in **Ask StayOps**. It cannot approve, reject, or resume a human-review action; approvals remain on-screen only.

Never commit API keys to the repository.

### Trace the Week 4 STAY-001 baseline with LangSmith

LangSmith tracing is opt-in and does not change router, specialist, synthesis,
safety, human-review, tool, or UI behavior. The first case intentionally keeps
the exact baseline query `Who is checking in tomorrow?` with a fixed reference
date of September 2, 2026.

Add the following configuration to `.env`:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY="replace-with-langsmith-api-key"
LANGSMITH_PROJECT=stayops-week4-eval
```

If the API key belongs to multiple workspaces, also set
`LANGSMITH_WORKSPACE_ID`. Accounts using a non-US LangSmith region should set
the corresponding `LANGSMITH_ENDPOINT`.

Export the environment and run the single case:

```bash
set -a
source .env
set +a
uv run python -m src.evaluation.langsmith_runner
```

The runner creates one root trace named `StayOps Evaluation Run`, prints the
expected-versus-actual baseline, and saves its run and trace identifiers to
`evaluation/results/langsmith/stay_001_baseline.json`. LangGraph nodes appear as
child runs, and each read-tool attempt is recorded as a child tool span.

The saved STAY-001 artifact records the original baseline mismatch. The current
implementation now recognizes `checking in`, activates only Booking, and keeps
the read-only request out of human approval. The frozen baseline remains
available for comparison with the post-improvement run.

### Run the Week 4 golden-dataset baseline

The frozen `evaluation/week4/golden_dataset_v1.json` contains 50 cases covering
happy paths, edge cases, deterministic failures, and adversarial safety checks.
The baseline runner uses each case's fixed reference date, creates a clean
checkpoint and temporary runtime overlay per case, never auto-approves a human
review, and leaves production behavior and source fixtures unchanged.

Validate the evaluators on the five prescribed cases first:

```bash
set -a
source .env
set +a
uv run python -m src.evaluation.golden_runner --validation
```

Run all 50 cases:

```bash
set -a
source .env
set +a
uv run python -m src.evaluation.golden_runner
```

Run one case or filter the dataset:

```bash
uv run python -m src.evaluation.golden_runner --case STAY-001 --no-tracing
uv run python -m src.evaluation.golden_runner --scenario failure --no-tracing
uv run python -m src.evaluation.golden_runner --domain booking --difficulty hard --no-tracing
```

Results are written to `evaluation/results/baseline-v1/` as detailed JSON,
flattened CSV, an aggregate JSON report, a human-readable Markdown summary, and
a raw failed-case inventory. Required-fact accuracy, specialist and tool
trajectory, HITL accuracy, failure recovery, latency, unauthorized writes, and
unsupported critical claims remain separate metrics; the runner does not
produce one opaque quality score.

Run the H1–H4 post-improvement evaluation without changing the frozen dataset
or scoring rules:

```bash
set -a
source .env
set +a
uv run python -m src.evaluation.golden_runner \
  --run-version improved-v1 \
  --output-dir evaluation/results/improved-v1
```

The improved summary and baseline comparison are in
[`evaluation/results/improved-v1/`](evaluation/results/improved-v1/).

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
