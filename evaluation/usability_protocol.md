# Five-minute host usability protocol

This protocol measures the product target that a host can identify and act on
important issues in under five minutes. Automated workflow latency is measured
separately and is not a substitute for this check.

## Setup

- Use a clean browser session and the fixed synthetic operating date
  `2026-08-28`.
- Start the app with `uv run streamlit run app.py` and wait until the dashboard
  is fully loaded before giving the participant access.
- Do not explain which properties need attention or which action to choose.

## Task and timing

Start the timer when the participant first sees the daily briefing. Ask them to:

1. identify the two properties needing the most immediate attention;
2. explain the evidence for the highest-priority issue;
3. choose an appropriate proposed action; and
4. Approve, Edit and reconfirm, or Reject it.

Stop the timer when the dashboard shows the recorded decision or simulated
execution. A run passes only when the participant correctly identifies Lake
House and Pine House, uses evidence linked to the selected issue, completes a
decision, and takes less than 300 seconds.

## Record

Record one row per run without real guest or participant personal information:

| Date | Build commit | Participant alias | Duration seconds | Correct properties | Evidence used | Decision completed | Pass |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| YYYY-MM-DD | commit SHA | host-01 | 0 | yes/no | yes/no | approve/edit/reject/no | yes/no |

Do not mark this target met from automated latency alone. Keep completed rows
with the release evidence and report the number of passing runs and median
duration.
