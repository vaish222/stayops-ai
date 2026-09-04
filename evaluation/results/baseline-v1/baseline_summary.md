# StayOps Week 4 Baseline Summary

Dataset: `v1`  
Run: `baseline-v1`  
Synthesizer: `deterministic`  
Cases: 50

## Primary metrics

- Operational Decision Accuracy: 92.0%
- Specialist Recall: 96.7%
- Specialist Precision: 70.0%
- Tool Recall: 97.7%
- Tool Precision: 78.0%
- Trajectory Pass Rate: 44.0%
- HITL Accuracy: 12.0%
- Safe Failure Recovery: 87.5%

## Safety guardrails

- Unauthorized Writes: 0
- Unsupported Critical Claims: 0
- Cases Requiring Human or LLM Review: 10

## Latency

- Average: 17.025 ms
- Median: 14.187 ms
- P95: 29.300 ms
- Maximum: 57.122 ms

## Breakdowns

### Scenario Type

- adversarial: 1/3 cases passed; operational accuracy 100.0%; trajectory 66.7%
- edge: 0/15 cases passed; operational accuracy 86.5%; trajectory 40.0%
- failure: 0/7 cases passed; operational accuracy 100.0%; trajectory 57.1%
- happy_path: 0/25 cases passed; operational accuracy 92.7%; trajectory 40.0%

### Domain

- booking: 0/9 cases passed; operational accuracy 100.0%; trajectory 0.0%
- change_context: 0/1 cases passed; operational accuracy N/A; trajectory 0.0%
- cross_domain: 0/3 cases passed; operational accuracy 69.5%; trajectory 33.3%
- daily_briefing: 0/2 cases passed; operational accuracy 100.0%; trajectory 100.0%
- date: 0/2 cases passed; operational accuracy 100.0%; trajectory 100.0%
- failure_recovery: 0/6 cases passed; operational accuracy 100.0%; trajectory 50.0%
- general: 0/1 cases passed; operational accuracy 100.0%; trajectory 100.0%
- guest: 0/5 cases passed; operational accuracy 80.0%; trajectory 80.0%
- maintenance: 0/6 cases passed; operational accuracy 100.0%; trajectory 66.7%
- property_scope: 0/1 cases passed; operational accuracy N/A; trajectory 0.0%
- risk: 0/1 cases passed; operational accuracy 83.3%; trajectory 100.0%
- safety: 1/3 cases passed; operational accuracy 100.0%; trajectory 66.7%
- synthesis_failure: 0/1 cases passed; operational accuracy 100.0%; trajectory 100.0%
- time_bound: 0/1 cases passed; operational accuracy 100.0%; trajectory 0.0%
- turnover: 0/8 cases passed; operational accuracy 81.2%; trajectory 12.5%

### Difficulty

- easy: 0/23 cases passed; operational accuracy 89.1%; trajectory 30.4%
- hard: 1/16 cases passed; operational accuracy 91.0%; trajectory 56.2%
- medium: 0/11 cases passed; operational accuracy 100.0%; trajectory 54.5%

## Baseline discipline

These results measure the existing StayOps implementation. No routing, agent, synthesis, safety, HITL, tool, fixture, or UI behavior was changed to improve scores.
