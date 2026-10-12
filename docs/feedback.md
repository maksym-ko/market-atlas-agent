# Learning from feedback

1. 👎 on an answer opens a form: what was wrong, and optionally "when I say *X* I mean indicator *CODE*".
2. That creates proposals: an eval-case candidate and, if given, an alias. Nothing changes yet.
3. A curator approves them at `/admin` (set `ADMIN_PASSWORD`). Approved aliases are used by indicator search right away. Approved cases go to `evals/candidates.jsonl` to become golden cases.

Feedback is also sent to LangSmith on the run that produced the answer.
