# Aggregation + Conversion Design Notes

Date: 2026-04-16
Status: In-progress thinking — not a design plan yet

## Context

Working through how aggregation should interact with conversion. Open tickets:

- scarnecchia/data-delivery-tide#6 — SAS-to-Parquet converter
- scarnecchia/data-delivery-tide#7 — Lexicon-driven aggregation service

Current state: #6 writes per-delivery Parquet, #7 reads those outputs and stacks them per lexicon. The question that surfaced: should aggregation be a distinct service at all, or should conversion produce the storage layout directly?

## Three candidate shapes

### A. Converter writes per-delivery. Aggregator builds the lake.

This is the current ticket state. Two services, each doing one thing. Aggregator owns hive layout, cross-workplan supersession, and current-view materialisation.

Cost: the aggregator's work is mostly file movement — converter writes per-delivery parquet, aggregator copies/stacks it into hive layout. No analytical work happens in aggregation. That smells like a service that shouldn't exist.

### B. Converter writes directly into hive layout, only for passing deliveries. Separate current-view materialiser.

Converter gates on status but writes to `proj_id/wp_type/wp_id/dp_id/ver_id/` partition paths instead of per-delivery directories. No stacking step — the hive layout *is* the stack, `pyarrow.dataset` reads it as one logical dataset. A small downstream service builds `current/` views by applying the supersession rule.

Aggregator as a distinct service disappears. Current-view materialisation remains.

### C. Converter converts everything regardless of status. Current-view materialiser filters + applies supersession.

Converter becomes fully dumb — sees a SAS file, writes a parquet partition, done. Status is no longer a conversion gate, just a filter in the materialiser.

Biggest write amplification. Maximum decoupling between registry state and file state.

## The wrinkle: pending data needs to be queryable

There is an internal human-in-the-loop QA review process that needs to query pending data before it reaches `passed`. This is a real use case.

Implications:

- **Rules out pure B as specced.** B only converts passing deliveries, so pending data never hits Parquet — QA reviewers have nothing to query.
- **Pushes toward C**, but C has real write amplification cost on healthcare data sizes.
- **Modified B is possible**: convert pending + passing, skip failed. Hive layout includes pending partitions; current-view filters them out; QA review tools query the partitioned tree directly with a status filter.

Not sure the QA review case alone justifies going back to A. It might justify "C, but scoped" — convert anything in an `actionable_statuses`-adjacent set, not literally everything.

## Cross-workplan supersession rule still needs a home

Independent of A/B/C choice: the rule "`wp002` supersedes `wp001` for the same `(proj, wp_type, dp_id)`" lives nowhere in code yet. `soc.qa:derive` only handles intra-workplan version supersession (verified in `src/pipeline/lexicons/soc/qa.py`).

Three possible homes:
- Aggregator / current-view materialiser — encodes the rule at read / materialisation time
- A new derive hook at `(proj, wp_type, dp_id)` scope — marks `wp001` as superseded when `wp002` passes
- A registry query mode — "give me the current row per `(proj, wp_type, dp_id)`" as a first-class endpoint

The current-view materialiser feels like the right home under shape B or C — it's already the service computing "what is current now."

## Sharp questions to resolve

1. **Which statuses justify converting?** `passed` only? `passed` + `pending` (for QA review)? Everything (for maximum decoupling)?
2. **Where does the cross-workplan supersession rule live?** Aggregator / materialiser, derive hook at broader scope, or registry query endpoint?
3. **What does `output_path` on a registry row mean under a hive layout?** A partition path? The root of the lexicon's dataset? A logical dataset URI?
4. **Does the QA review tooling warrant its own lexicon-aware read path, or does it query the partitioned tree directly?** If the latter, the current-view materialiser just becomes one of several consumers of the hive layout, not the sole entry point.
5. **What is the blast radius of write amplification under C or modified-B?** Order-of-magnitude estimate on how much pending / non-passing data exists in a typical period vs passing data.

## Current lean (subject to change)

Modified B: convert `passed` + `pending` into the hive layout. Current-view materialiser applies cross-workplan supersession to produce a `current/` view per lexicon. QA review tooling queries the partitioned tree with a status filter; analytical consumers read `current/`.

This collapses aggregation into "where does conversion write" plus "one more service that materialises the current view," which is substantively less surface area than shape A. The converter's `output_path` contract changes from per-delivery directory to partition path.

## Follow-ups

- If modified B wins: revise #6 to specify hive-layout output, collapse or redirect #7 toward current-view materialisation.
- If A wins: keep tickets roughly as-is, finalise the supersession rule location.
- Either way: need an estimate on pending-vs-passing data volume before committing to converting pending data.
