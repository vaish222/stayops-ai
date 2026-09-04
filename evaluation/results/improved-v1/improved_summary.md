# StayOps Week 4 Improved Summary

Dataset: `v1`  
Run: `improved-v1`  
Synthesizer: `deterministic`  
Cases: 50

## Primary metrics

- Operational Decision Accuracy: 94.4%
- Specialist Recall: 100.0%
- Specialist Precision: 95.3%
- Tool Recall: 100.0%
- Tool Precision: 95.6%
- Trajectory Pass Rate: 94.0%
- HITL Accuracy: 100.0%
- Safe Failure Recovery: 100.0%

## Safety guardrails

- Unauthorized Writes: 0
- Unsupported Critical Claims: 0
- Cases Requiring Human or LLM Review: 10

## Latency

- Average: 14.516 ms
- Median: 11.720 ms
- P95: 32.367 ms
- Maximum: 55.831 ms

## Breakdowns

### Scenario Type

- adversarial: 3/3 cases passed; operational accuracy 100.0%; trajectory 100.0%
- edge: 12/15 cases passed; operational accuracy 96.2%; trajectory 86.7%
- failure: 6/7 cases passed; operational accuracy 100.0%; trajectory 85.7%
- happy_path: 22/25 cases passed; operational accuracy 92.0%; trajectory 100.0%

### Domain

- booking: 9/9 cases passed; operational accuracy 100.0%; trajectory 100.0%
- change_context: 0/1 cases passed; operational accuracy N/A; trajectory 0.0%
- cross_domain: 2/3 cases passed; operational accuracy 83.3%; trajectory 100.0%
- daily_briefing: 2/2 cases passed; operational accuracy 100.0%; trajectory 100.0%
- date: 2/2 cases passed; operational accuracy 100.0%; trajectory 100.0%
- failure_recovery: 5/6 cases passed; operational accuracy 100.0%; trajectory 83.3%
- general: 1/1 cases passed; operational accuracy 100.0%; trajectory 100.0%
- guest: 4/5 cases passed; operational accuracy 80.0%; trajectory 100.0%
- maintenance: 6/6 cases passed; operational accuracy 100.0%; trajectory 100.0%
- property_scope: 0/1 cases passed; operational accuracy N/A; trajectory 0.0%
- risk: 1/1 cases passed; operational accuracy 100.0%; trajectory 100.0%
- safety: 3/3 cases passed; operational accuracy 100.0%; trajectory 100.0%
- synthesis_failure: 1/1 cases passed; operational accuracy 100.0%; trajectory 100.0%
- time_bound: 1/1 cases passed; operational accuracy 100.0%; trajectory 100.0%
- turnover: 6/8 cases passed; operational accuracy 87.5%; trajectory 100.0%

### Difficulty

- easy: 20/23 cases passed; operational accuracy 91.3%; trajectory 100.0%
- hard: 13/16 cases passed; operational accuracy 95.8%; trajectory 87.5%
- medium: 10/11 cases passed; operational accuracy 100.0%; trajectory 90.9%

## Improved discipline

These results measure the approved H1–H4 implementation against the unchanged golden dataset and scoring rules.
