---
name: literature-review
title: Running a literature review that finds the gap
description: Search, screen, extract, synthesise and map a body of literature — including how to handle paywalls and predatory venues honestly.
tags: literature, review, research, sources, citations, synthesis, gap
---

A literature review is not a list of summaries. It is an argument about what is
known, what is contested, and what is missing. Structure the work so the gap
falls out of the evidence.

## 1. Turn the topic into searchable concepts

Break the question into 2–4 concept blocks, and list synonyms for each. For
Tanzanian research, include local terminology and Kiswahili terms — a search in
English alone will miss the national literature entirely.

> Concept A: smallholder farmer, mkulima mdogo, small-scale agriculture
> Concept B: drought, ukame, water stress, rainfall variability
> Concept C: adaptation, coping strategy, resilience

Search combinations, not the whole sentence. Use `search_library` for the local
academic corpus first, then `web_search` / `deep_research` for the wider
literature. The local corpus is the one that will actually answer a question
about Tanzania.

## 2. Screen in two passes

- **Pass 1, title and abstract.** Decide in-scope or not against explicit
  criteria you write down FIRST (population, geography, date range, study type).
  Record how many you excluded and why — that count belongs in the write-up.
- **Pass 2, full text.** Only for those that survived pass 1.

Say plainly when a source is paywalled and you could only read the abstract. Do
not summarise a paper's findings from its abstract as though you read the
methods. `check_citation` before relying on a reference.

## 3. Watch the venue

Some journals are flagged as predatory in this library. If a flagged source
carries a claim, say so before it is cited — a review built on unrefereed work
inherits its problems. Do not silently drop such sources either; note them and
their status.

## 4. Extract into a table, not prose

One row per study: citation, setting, population and n, design, key measure,
finding, limitation. Building this table is what makes synthesis possible — it
turns twenty papers into something you can compare down a column.

## 5. Synthesise by theme, never by paper

The failure mode is one paragraph per study in the order you found them. Instead
organise by what the literature is arguing about:

- Where do studies agree, and is that agreement independent or are they all
  citing the same original source?
- Where do they disagree, and does the disagreement track method, setting, or
  period?
- What has never been measured in this setting at all?

## 6. Map it

Build a `create_knowledge_graph` with groups `Theory` / `Method` / `Finding` /
`Gap`, edges labelled `builds on`, `contradicts`, `replicates`. See the
`knowledge-graph` skill. The `Gap` nodes are the deliverable — they are what the
researcher's own work will address.

## 7. State the gap as a claim

Finish with: what is missing, why it matters, and what study would close it.
Then say how confident you are, and what would change your mind. A review that
cannot be wrong has not said anything.
