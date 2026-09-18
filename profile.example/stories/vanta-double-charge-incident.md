---
id: vanta-double-charge-incident
title: The double-charge incident
status: verified
source: import
role: Vanta Pay
tags:
- incident
- postmortem
- postgres
- observability
aliases:
- outage
- incident
- postmortem
- production bug
- on-call
- root cause
- failure story
- customer impact
- mistake
- went wrong
- hardest bug
metric: 1,400 customers
verified: '2026-02-11'
---

## Claim

Led the postmortem on a double-charge incident affecting 1,400 customers, tracing it to a retry path that bypassed the ledger's uniqueness constraint.

## Situation

Support escalated a handful of duplicate charges on a Monday. By the time I queried the ledger it was 1,400 customers over about nine hours.

## Task

Stop the bleeding, size the blast radius honestly, then find out why a constraint we believed was protecting us had not.

## Action

Killed the offending worker first and reconciled refunds before diagnosing - the order mattered, because the backlog was still draining. The cause: a batch settlement job wrote through a different code path that built its insert by hand and never included the idempotency key column. The constraint existed; that path simply did not populate the column it covered. I wrote the query that sized the impact and the postmortem.

## Result

All 1,400 refunded within two days. I added a check constraint making the key non-nullable, which turned the class of bug from silent to loud at write time.

## Reflection

The lesson I actually took was about the shape of the failure, not the bug. We had a correct constraint and a second write path nobody remembered. Now when I add an invariant I grep for every writer to that table rather than trusting the one I am looking at.
