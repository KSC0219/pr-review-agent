# Evaluation

## Dataset

`eval/dataset.py` defines 26 small pull requests against a Spring Boot codebase.

| Group | Cases | What is planted |
|---|---|---|
| Bugs | 8 | `==` on strings, `Optional.get()`, off-by-one, resource leak, swallowed exception, integer division, null map value, modifying a list while iterating |
| Security | 8 | SQL injection, hardcoded secret, password in log, MD5 hashing, path traversal, removed authorization, command injection, insecure random token |
| Missing tests | 4 | New public method or endpoint with no test in the PR |
| Clean | 6 | Rename, parameterized query, logging, constant extraction, Javadoc, test-only change |

Each defect is labelled with a category and the exact added line it sits on.
Clean cases have no labels, so every comment on them is a false positive.

## Metrics

- **True positive:** a finding in the right file, with the right category, within 2 lines of the label.
- **Recall:** defects caught / 20 planted defects.
- **Precision:** true positives / all findings posted.
- **Clean PRs with no comments:** how many of the 6 clean PRs got zero findings.
- **Cost and latency per PR**, from the token usage of the three agent calls.
- **Dropped by guardrail:** findings removed because they pointed at a line the PR did not add.

Scoring is strict on purpose. A security agent that also comments "no test for this" on a bug case
gets a false positive for it.

## Running

```bash
python eval/run_eval.py --llm baseline              # no key needed
python eval/run_eval.py --llm anthropic             # needs ANTHROPIC_API_KEY
python eval/run_eval.py --llm anthropic --only sec  # just the security cases
```

Results are written to `eval/results/<llm>.json` with a per-case breakdown.

## Results

### Rule-based baseline

| Metric | Value |
|---|---|
| Recall | 60% (12 of 20) |
| Precision | 100% (0 false positives) |
| Clean PRs with no comments | 6 of 6 |
| Bugs caught | 3 of 8 |
| Security issues caught | 5 of 8 |
| Missing tests caught | 4 of 4 |

Missed by the baseline: off-by-one loop, resource leak, integer division, null map value,
concurrent modification, path traversal, removed authorization, insecure random token.
None of these has a reliable textual signature; they need an understanding of what the code does.

### LLM agents

Not recorded yet. Run `python eval/run_eval.py --llm anthropic` and paste the summary here.
Record the model id and date with the numbers, since they change between models.

| Metric | Value |
|---|---|
| Model | |
| Recall | |
| Precision | |
| Clean PRs with no comments | |
| Avg cost per PR | |
| Avg latency per PR | |
| Dropped by guardrail | |

### Error analysis template

After the LLM run, look at each false negative and false positive in `eval/results/anthropic.json` and note:

1. Which agent was responsible.
2. Whether it was a prompt problem (agent stepped outside its job), a location problem (right issue, wrong line) or a knowledge problem.
3. What prompt or rule change fixed it, and the recall/precision before and after.

## Limitations

- 26 cases is small. One case moves recall by 5 points.
- The PRs are synthetic and short. Real PRs are longer, span many files and have subtler defects.
- The baseline rules were written with knowledge of the defect types, so its score here is optimistic.
- The "missing tests" label is a judgement call; a reasonable reviewer could flag untested code in the bug cases too.
