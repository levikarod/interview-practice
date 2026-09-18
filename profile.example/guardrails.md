# Guardrails

Things that get flagged as `risky_claims` if they turn up in an answer.

Two kinds live here. **Blocked claims** are things that are not true, or not
yours, and will collapse under one follow-up question. **Numbers to defend** are
figures on your CV with nothing behind them — they are not lies, but you need an
answer ready for "how did you measure that?"

The onboarding step seeds the second list automatically from CV bullets whose
metric has no stated source. The first list you write yourself, usually right
after an interview goes badly.

> Sample data — Mara Okonjo is fictional. Yours lives in `profile/guardrails.md`.

## Blocked claims

- **"I designed the ledger schema."** I did not. I partitioned an existing table.
  The original schema predates me by two years. Say "I partitioned it" and name
  the constraint I worked within.

- **"We were fully event-driven."** Kafka carried settlement events only. The
  authorisation path was synchronous HTTP throughout. Claiming otherwise invites
  questions about ordering guarantees I never had to solve.

- **"I led the migration."** On the fraud-vendor work I wrote the adapter and did
  the cutover; the decision and the vendor negotiation were my staff engineer's.
  "I built and shipped it" is true. "I led it" is not.

- **Anything about Kubernetes internals.** I deploy to it and read its logs. I
  have never debugged a control-plane problem, written an operator, or tuned a
  scheduler. If a question goes there, say so early rather than three questions in.

## Numbers to defend

- **"200ms p99 write latency"** — from a Datadog dashboard I no longer have
  access to. I am confident about the shape of the problem, less so about the
  exact figure. If pushed: say it was "comfortably over 100ms and climbing."

- **"400M rows"** — right order of magnitude, not a number I verified at the time.

- **"Mean time to acknowledge, hours to under ten minutes"** — the "under ten
  minutes" is measured from PagerDuty. The "hours" baseline is my impression of
  what it was like before, not an instrumented figure. Do not present both halves
  as equally solid.

- **"1,400 customers"** — this one is solid. It came from the incident report and
  I wrote the query. Defend it without hedging.
