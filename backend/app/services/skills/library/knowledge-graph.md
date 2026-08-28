---
name: knowledge-graph
title: Building a knowledge graph with React Flow
description: How to turn a topic, a literature set or an argument into an explorable node-edge graph that teaches rather than decorates.
tags: graph, react-flow, concept map, literature, network, relationships
---

Use `create_knowledge_graph` whenever the answer is a set of **entities and the
relationships between them** and the reader should explore it: a literature map,
a causal chain, a syllabus topic map, an argument structure, the parts of a
system, a timeline of influence.

Prefer it over `create_diagram` when the reader benefits from panning, searching
and clicking for detail. Prefer `create_diagram` when a fixed picture is enough
and printability matters.

## The one rule the renderer enforces

**Every edge endpoint must be an id that exists in `nodes`.** A dangling edge
rejects the whole call. Build your node list first, then write edges against it.

## Designing the graph

A graph with 60 undifferentiated nodes teaches nothing. Aim for **8–25 nodes**
for a teaching graph; go higher only for a genuine literature map, and then lean
on groups and search.

- **`id`**: short, stable, lowercase (`calvin`, `nbs-2022`). You will type it
  again in the edges.
- **`label`**: what the reader reads. Two to four words. Not a sentence.
- **`group`**: this is what colours the node and generates the legend. Choose
  groups that carry meaning — `Input`/`Process`/`Output`, `Theory`/`Evidence`/
  `Gap`, `Cause`/`Mechanism`/`Effect`. Keep to ≤ 5 groups.
- **`detail`**: one or two sentences, shown in the side panel on click. This is
  where the substance goes — it lets the graph stay readable while still
  carrying depth.
- **`url`**: link the source when the node IS a source.
- **Edge `label`**: name the relationship, and make it a verb —
  `causes`, `measures`, `contradicts`, `builds on`, `is a`. An unlabelled edge
  says only "these are related", which the reader could already see.

## Layout

- `lr` (default) — a process or causal flow read left to right.
- `tb` — a hierarchy, taxonomy or syllabus tree.
- `radial` — one central concept with everything hanging off it. The most
  connected node becomes the hub automatically.
- `preset` — you supply `x`/`y` because the geometry itself means something (a
  map, a matrix, a timeline).

## Worked shape: a literature map

- Groups: `Theory`, `Method`, `Finding`, `Gap`.
- One node per paper, `label` = author + year, `detail` = the claim in one
  sentence, `url` = the source.
- Edges: `builds on`, `contradicts`, `replicates`, `measures`.
- The `Gap` nodes are the point of the whole exercise — they are what the
  researcher's own work will address. Make sure at least one exists, and say in
  prose which gap you think is most defensible and why.

## Always

Say in prose what the graph shows, which cluster matters, and what the reader
should notice. Then `verify_artifact`. A graph the reader has to interpret
unaided is a picture of your notes, not an answer.
