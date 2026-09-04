# StayOps Week 4 Failed Improved Cases

## STAY-010

- Query: Does Ellis Harbor have an unanswered message before the September 5 Lake House arrival?
- Scenario: happy_path
- Domain: guest
- Difficulty: easy
- Failed checks: required_fact_recall, operational_decision_accuracy
- LangSmith trace ID: 8d8b0033-0c01-4b2a-a77c-f2ae198b0674

## STAY-014

- Query: Is Garden Cottage cleaning confirmed for September 12?
- Scenario: happy_path
- Domain: turnover
- Difficulty: easy
- Failed checks: overall_status_correct, operational_decision_accuracy
- LangSmith trace ID: d14407b5-4835-462a-b8e7-7b8581c1cdf9

## STAY-015

- Query: Is Pine House pre-arrival cleaning confirmed for September 14?
- Scenario: happy_path
- Domain: turnover
- Difficulty: easy
- Failed checks: overall_status_correct, operational_decision_accuracy
- LangSmith trace ID: 732c28d7-c59b-4cb7-bd11-ca5c400434a3

## STAY-027

- Query: How are things looking at the lake property?
- Scenario: edge
- Domain: property_scope
- Difficulty: medium
- Failed checks: specialist_precision, tool_precision, trajectory_pass
- LangSmith trace ID: eb5b844b-1ec8-4cdb-b5d4-cd7da5fd86ae

## STAY-029

- Query: Is everything ready before the next Lake House guest arrives?
- Scenario: edge
- Domain: cross_domain
- Difficulty: hard
- Failed checks: overall_status_correct, operational_decision_accuracy
- LangSmith trace ID: 1e2bd167-aa50-4dc7-bb26-1804ed7bce9a

## STAY-040

- Query: What changed for City Loft?
- Scenario: edge
- Domain: change_context
- Difficulty: hard
- Failed checks: specialist_precision, tool_precision, trajectory_pass
- LangSmith trace ID: b92f0c03-cea6-4990-8473-6abb3e14f525

## STAY-045

- Query: Is Garden Cottage ready for today's arrival?
- Scenario: failure
- Domain: failure_recovery
- Difficulty: hard
- Failed checks: specialist_precision, tool_precision, trajectory_pass
- LangSmith trace ID: 09f93dd6-2d4d-4fc8-ac7c-95f77a156bd8
