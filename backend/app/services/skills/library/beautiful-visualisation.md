---
name: beautiful-visualisation
title: Designing a visualisation that reads as deliberate
description: Palette, chart choice, layout and labelling rules that make a generated visual look designed rather than defaulted.
tags: charts, design, palette, colour, dataviz, figures
---

Most generated charts fail the same way: each one is individually fine and
together they share no visual language, so the set reads as automated. These are
the decisions that fix that. Apply them to every visual you produce.

## 1. Choose the form before the colours

Pick by what the reader must DO, not by what looks impressive.

| The reader must… | Use |
|---|---|
| compare magnitudes across categories | horizontal bars, sorted by value |
| see a trend over time | line; one line per series, max ~5 |
| see a distribution | histogram, or a box/strip plot if comparing groups |
| see a relationship between two variables | scatter, with a fitted line only if you state the model |
| see parts of a whole | stacked bar — **not** a pie, unless there are exactly 2–3 parts |
| understand how an outcome responds to a parameter | `create_simulation`, not a chart |
| explore entities and their relationships | `create_knowledge_graph` |

Sort bars by value, never alphabetically, unless the category order is itself
meaningful (months, school forms, Likert levels).

## 2. The palette rule

The render service already applies Weave's house theme. Do not override it with
your own colours unless the data demands it. When it does:

- **Categorical**: use the house series in order. Orange leads; everything else
  is a warm or cool neutral that recedes behind it. Never a rainbow — a rainbow
  implies an ordering that categorical data does not have.
- **Sequential** (low→high): one hue, varying lightness. Light = low.
- **Diverging** (below/above a meaningful midpoint): two hues meeting at a
  neutral centre. Only use this when there IS a real midpoint (zero, the
  national average, no change).
- **Maximum 5 colours** in one chart. If you need more, you need a different
  chart — usually small multiples.
- Colour must never be the only carrier of meaning: also vary position, order,
  or add a direct label. Roughly 1 in 12 men has a colour-vision deficiency.

## 3. Labelling is most of the design

- Title states the FINDING, not the variables: "Maize yield fell 23% after
  2019", not "Yield by year".
- Label the axes with units. Every time. `Yield (tonnes/ha)`.
- Prefer direct labels on the lines/bars over a legend. A legend makes the
  reader's eye travel; a direct label does not.
- Cite the source under the chart when the data came from a retrieved source.
- Do not print more precision than the data carries. 23%, not 23.4718%.

## 4. Restraint

Remove: gridlines heavier than hairlines, chart borders, drop shadows, 3D
effects on 2D data, background fills, and any decoration that encodes nothing.
Whitespace is not wasted space.

## 5. Always interpret

Never emit a visual without saying, in prose, what it shows and what the reader
should notice. An uninterpreted chart makes the reader do your work.

## 6. Verify

Charts are artifacts. After generating, `verify_artifact` — a page that renders
blank looks exactly like one that renders perfectly until someone opens it.
