---
id: vanta-idempotency-keys
title: Idempotency keys on the authorisation API
status: verified
source: import
role: Vanta Pay
tags:
- idempotency
- api-design
- postgres
- distributed-systems
aliases:
- exactly-once
- deduplication
- retries
- at-least-once
- safe retries
- payment correctness
- race conditions
- concurrency
- double charge
verified: '2026-02-11'
---

## Claim

Designed idempotency keys for the authorisation API so a retried request never double-charges, replacing a client-side dedup scheme that leaked.

## Situation

Clients retried failed authorisations on their own timers. The old scheme deduplicated in the client SDK, which meant any caller not using our SDK - and the ones who wrote their own integration were our largest merchants - had no protection at all.

## Task

Make a retried authorisation safe regardless of who sends it, without adding latency to the happy path.

## Action

Callers send an Idempotency-Key header. We store it in a dedicated table with a unique constraint and the hash of the request body, inside the same transaction that writes the authorisation. A replay with the same key returns the stored response; a replay with the same key but a different body is a 422 rather than a silent overwrite, because that means a client bug and hiding it helps nobody.

## Result

Double-charges from retries went to zero. The 422 path caught two real client bugs in the first month that the old scheme had been silently absorbing.

## Reflection

The part I got wrong first: I initially keyed only on the header and let the body vary. That is the version most people describe when asked about idempotency, and it turns a client bug into a wrong charge. Hashing the body is what makes it safe rather than merely deduplicated.
