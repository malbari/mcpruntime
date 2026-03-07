# PTC-Bench: Programmatic Tool Calling Report (OPENSANDBOX)

*Evaluating code-first tool calling approach*

*Results use **LLM-generated code** (agent evaluation).*

## Agent Performance Summary
- **Task Success Rate**: 65.0% (39/60 attempted, 0 skipped)
- **Avg Time-to-Success**: 18.90s (includes LLM generation)
- **Avg Iterations Needed**: 2.0
- **Avg LLM Generation Time**: 12.78s
- **Execution Time (substrate)**: 7.19s
- **P95 Execution Time**: 9.43s
- **Errors/Timeouts**: 21 / 0

## Category Breakdown (Agent Success Rates)
| Category | Tasks | Success | Skipped | Success Rate | Avg TTS |
|----------|-------|---------|---------|--------------|---------|
| ptc | 60 | 39 | 0 | 65.0% | 7.19s |

*Success Rate = % of tasks where agent-generated code passed validation*

## Difficulty Breakdown
| Difficulty | Total | Passed | Skipped | Pass Rate | Avg Time |
|------------|-------|--------|---------|-----------|----------|
| easy | 18 | 14 | 0 | 77.8% | 6.10s |
| hard | 25 | 12 | 0 | 48.0% | 7.97s |
| medium | 17 | 13 | 0 | 76.5% | 7.20s |

## Agent Task Failures

Tasks where the LLM-generated code failed validation or execution:

- **PTC05** (ptc): [Validation] Validation failed: output did not meet minimum score require...
- **PTC06** (ptc): [Validation] Validation failed: output did not meet minimum score require...
- **PTC09** (ptc): [Validation] Validation failed: output did not meet minimum score require...
- **PTC14** (ptc): [Validation] Validation failed: output did not meet minimum score require...
- **PTC36** (ptc): [Validation] Validation failed: output did not meet minimum score require...
- **PTC37** (ptc): [Validation] Validation failed: output did not meet minimum score require...
- **PTC38** (ptc): [Validation] Validation failed: output did not meet minimum score require...
- **PTC39** (ptc): [Validation] Validation failed: output did not meet minimum score require...
- **PTC42** (ptc): [Validation] Validation failed: output did not meet minimum score require...
- **PTC43** (ptc): [Validation] Validation failed: output did not meet minimum score require...
- *...and 11 more.*
