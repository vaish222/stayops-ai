# StayOps Week 4 Improvement Comparison

The frozen `golden_dataset_v1.json` and evaluator scoring rules were used for
both runs.

| Metric | Baseline v1 | Improved v1 | Change |
|---|---:|---:|---:|
| Cases passed | 1/50 | 43/50 | +42 cases |
| Operational Decision Accuracy | 92.04% | 94.44% | +2.40 pp |
| Specialist Recall | 96.67% | 100.00% | +3.33 pp |
| Specialist Precision | 70.00% | 95.33% | +25.33 pp |
| Tool Recall | 97.67% | 100.00% | +2.33 pp |
| Tool Precision | 78.00% | 95.60% | +17.60 pp |
| Trajectory Pass Rate | 44.00% | 94.00% | +50.00 pp |
| HITL Accuracy | 12.00% | 100.00% | +88.00 pp |
| Safe Failure Recovery | 87.50% | 100.00% | +12.50 pp |
| Unauthorized Writes | 0 | 0 | unchanged |
| Unsupported Critical Claims | 0 | 0 | unchanged |
| P95 Latency | 29.300 ms | 32.367 ms | +3.067 ms |

All required thresholds pass in `improved-v1`. Seven cases remain in
`failure_cases.md`; these are retained rather than hidden by changing the golden
labels or scoring rules.

## Hypothesis attribution map

| Hypothesis | Primary code boundary | Focused tests |
|---|---|---|
| H1 | `src/safety/risk_gate.py`, risk output advisories | `tests/test_improvement_h1_approval_policy.py` |
| H2 | `src/agents/request_operation.py`, specialist/source policy | `tests/test_improvement_h2_specialist_policy.py` |
| H3 | `src/agents/request_router.py`, `src/time_context.py` | `tests/test_improvement_h3_normalization.py` |
| H4 | `src/safety/readiness_policy.py` | `tests/test_improvement_h4_readiness_policy.py` |

