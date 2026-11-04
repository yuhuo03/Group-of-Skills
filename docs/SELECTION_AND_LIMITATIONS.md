# Selection, history, and limitations

## Exactly which experiments generated this table?

| Benchmark | Tasks per method | Selected trials | Selection |
|---|---:|---:|---|
| SkillsBench | 86 | 430 | Four audited baseline arms plus the complete GoSkills candidate-D cohort |
| ALFWorld | 134 | 670 | Five methods, one selected r1 trial per task/method |
| Terminal-Bench 2 | 89 | 445 | Original selected results, replacing only 45 originally-zero GoSkills cells with their full rerun cohort |

Method IDs: `noskills`, `vanilla`, `vector`, `native-gos` (Graph of Skills), `goskills-d` (GoSkills D). SkillsBench source labels `vanilla-filesystem` and `goskills` are normalized to `vanilla` and `goskills-d` respectively. No other candidate GoSkills cohort is substituted.

## TB2 lineage

1. The pre-replacement selected table contained 445 valid scores. Its recovery history includes retained older results, authorized retries of 13 unresolved attempts, and separate cleanup recoveries. It must not be described as 445 pristine first attempts.
2. GoSkills had 44 positive and45 zero selected scores (44/89=49.4382%). The user requested one further attempt for each of those45 zero cells. The44 positive cells were not repeated.
3. r14 dispatched15 tasks. Fourteen had normal valid receipts; `filter-js-from-html` produced reward0 and an agent-completed record, then cleanup refused a still-running container. Its original PROCESS_FAILED receipt is retained; later strict non-force cleanup has a separate receipt.
4. r15 ran exactly the30 r14 never-dispatched tasks. It did not repeat those15 tasks. All30 ended with valid scores.
5. All45 repeat results are used, including35 zeros, not only the10 gains. Together with the44 retained positives the selected score is54/89=60.6742%.
6. The current TB2 token/runtime mean uses the same89 selected attempts as the accuracy. The costs of superseded attempts are not silently added to those89-task means. They are also not claimed to disappear from real total expenditure.

## Interpretation that is supported / not supported

- Supported: the selected replacement table and its descriptive token/runtime means; 10/45 originally-zero tasks scored1 in the rerun cohort.
- Not established: that all original zero scores were API failures; that the rerun gain is caused by an API fix; that an equally repeated No Skills arm would retain its original score.
- Selective rerunning only one method's failures creates asymmetric sampling and an upward selection effect relative to untouched single-attempt baselines. Keep the original table as the like-for-selected-history reference, disclose the replacement table as a conditional repeat analysis, and avoid presenting60.7% as an untouched single-pass superiority estimate.
- These are single selected runs, not a three-seed mean or confidence interval. Do not invent ±standard deviations from these rows.
- SkillsBench candidate D was developed with observed experiment feedback. This package does not establish an untouched holdout protocol.
- Runtime mixes retained runs and later recovery hosts/cache conditions; it is descriptive recorded latency, not a controlled causal efficiency test.
- Model evidence identifies the returned snapshot `gpt-5.4-2026-03-05`; a hosted API can change outside this archive. Bitwise deterministic live reruns are not promised.

## What “full trace” means here

For SkillsBench/TB2 it means recorded `agent/trajectory.json`, along with available API calls, retrievals, command-event metadata, configs and verifier outputs. For ALFWorld it means `result.json.messages` plus `api_calls.json`, retrievals and transport records. It is not an assertion that every intermediate container filesystem snapshot was captured.

Some canonical scoring files are noncanonical JSON. They are preserved as text with the parse issue recorded; the artifact builder does not repair or substitute their contents. Full verifier success does not retroactively prove all environment conditions ideal.
