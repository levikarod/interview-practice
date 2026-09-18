---
id: rota-queue-backpressure
title: Backpressure on the dispatch queue
status: verified
source: import
role: Rota Logistics
tags:
- queues
- backpressure
- rabbitmq
- load-shedding
aliases:
- rate limiting
- throttling
- load shedding
- queue depth
- flow control
- overload
- scaling
- peak traffic
- capacity
- black friday
- graceful degradation
verified: '2026-02-11'
---

## Claim

Added backpressure to the dispatch queue after a Black Friday backlog, so the system shed load predictably instead of timing out across the board.

## Situation

On Black Friday, orders arrived about four times faster than couriers could absorb. The dispatch queue grew unbounded, matching latency went past the point where a match was still useful, and customers got couriers assigned to orders they had already cancelled.

## Task

Make overload degrade in a way we could explain to operations, rather than failing everywhere at once.

## Action

Two changes. A bounded queue with a shallow depth, so producers block rather than buffer indefinitely. And a deadline on each order: past it the order leaves the queue and goes to a 'no courier available' state the customer sees immediately. The second one was the argument - operations wanted infinite retry, and a stale match is worse than an honest no.

## Result

Peak-day behaviour became legible: a known fraction of orders got a fast honest rejection, and everything accepted was matched inside the deadline.

## Reflection

I would push harder on the product conversation earlier. The technical change took two days; agreeing that rejecting orders was acceptable took three weeks, and that was the real work.
