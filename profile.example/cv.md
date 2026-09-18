# Mara Okonjo

**Backend Engineer**

- Email: mara@example.com
- Location: Lisbon, Portugal

<!-- ==========================================================================
     THIS IS SAMPLE DATA. Mara Okonjo is fictional.

     It exists so a fresh clone of this repo runs immediately instead of showing
     an empty screen. Your own material goes in `profile/`, which is gitignored.

     This file also shows the format `core.ingest` generates from a CV PDF: prose
     for humans, plus a <!--meta --> block per bullet carrying the machine-
     readable fields. `cv.json` is derived from these blocks; this file is the
     source of truth. Edit here, re-derive from here.
     ========================================================================== -->

## Summary

Backend engineer, 7 years, mostly Python and Go in payments and logistics. Spent
three years on a card-payments platform where correctness under retry was the
whole job, then two years at a logistics startup owning the dispatch pipeline.

## Experience

### Senior Backend Engineer, Payments Platform team, Vanta Pay (Remote) (2022 - Present)

Card payments processor, ~200 people. My team owned the authorisation path and
the ledger.

- Designed idempotency keys for the authorisation API so a retried request never
  double-charges, replacing a client-side deduplication scheme that leaked.

<!--meta
id: vanta-idempotency-keys
skills: idempotency, API design, PostgreSQL, distributed systems
aliases: exactly-once, deduplication, retries, at-least-once, safe retries, payment correctness, race conditions
metric: none
metric_sourced: true
-->

- Led the postmortem on a double-charge incident affecting 1,400 customers,
  tracing it to a retry path that bypassed the ledger's uniqueness constraint.

<!--meta
id: vanta-double-charge-incident
skills: incident response, postmortems, PostgreSQL, observability
aliases: outage, incident, postmortem, production bug, on-call, root cause, failure story, customer impact
metric: 1,400 customers
metric_sourced: true
-->

- Partitioned the ledger table by month after write latency degraded past 200ms
  at the p99, keeping query plans stable as the table crossed 400M rows.

<!--meta
id: vanta-ledger-partitioning
skills: PostgreSQL, partitioning, query performance, capacity planning
aliases: database scaling, sharding, partitioning, p99 latency, query optimization, large tables, performance tuning
metric: 200ms p99, 400M rows
metric_sourced: false
-->

- Migrated the fraud-scoring vendor behind an adapter interface, so swapping
  providers took a config change rather than a rewrite of the auth path.

<!--meta
id: vanta-fraud-vendor-migration
skills: adapter pattern, vendor migration, API design, Go
aliases: third-party integration, vendor lock-in, abstraction layer, provider swap, interface design, decoupling
metric: none
metric_sourced: true
-->

**Tech stack:** Python, Go, PostgreSQL, Kafka, Redis, Docker, Kubernetes, AWS, Datadog.

### Backend Engineer, Dispatch team, Rota Logistics (Lisbon) (2020 - 2022)

Same-day delivery startup, 30 people. I owned the dispatch pipeline that matched
orders to couriers.

- Added backpressure to the dispatch queue after a Black Friday backlog, so the
  system shed load predictably instead of timing out across the board.

<!--meta
id: rota-queue-backpressure
skills: queues, backpressure, RabbitMQ, load shedding, Python
aliases: rate limiting, throttling, load shedding, queue depth, flow control, overload, scaling, peak traffic, capacity
metric: none
metric_sourced: true
-->

- Set up the on-call rotation and runbooks for a team that had none, cutting
  mean time to acknowledge from hours to under ten minutes.

<!--meta
id: rota-oncall-rotation
skills: on-call, runbooks, incident process, team process
aliases: on-call, operations, SRE, process improvement, documentation, team leadership, MTTA, reliability culture
metric: hours to under ten minutes
metric_sourced: false
-->

**Tech stack:** Python, RabbitMQ, PostgreSQL, Redis, Terraform, GCP.

## Skills

- **Backend:** Python, Go, REST APIs, event-driven systems, background workers
- **Data:** PostgreSQL, Redis, Kafka, RabbitMQ
- **Infra:** Docker, Kubernetes, Terraform, AWS, GCP, Datadog
- **Languages:** English (native), Portuguese (B2)
