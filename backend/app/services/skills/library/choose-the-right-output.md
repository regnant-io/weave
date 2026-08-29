---
name: choose-the-right-output
title: Deciding what to actually make before you make it
description: Which surface a request belongs on — an artifact, workspace software, an analysis, or prose — and which tool inside it. The decision that goes wrong before any code is written.
tags: planning, surface, artifact, workspace, tools, decision, orientation
---

Almost every badly-answered request here was decided wrongly before a line was
written. "Build me an interactive solar system I can fly through" gets answered
by writing an `index.html` into the workspace, downloading a copy of a 3D
library by hand, and trying to start a server nobody can reach — when one
`create_3d_experience` call produces a verified, interactive scene inline in the
conversation.

The tools were all available. Nothing said which surface the work belonged on.
Decide that first, in one sentence, before anything else.

## Four surfaces

**ARTIFACT** — something the user looks at or interacts with *inside this
conversation*. Rendered inline, verified in a real browser automatically, one
tool call. This is the right answer for almost anything the user wants to SEE or
PLAY WITH. Do not build it as files. Do not write an `index.html`. Do not start
a server.

**WORKSPACE** — a real codebase the user will download and run: several source
files, dependencies, tests, a package. Only when the deliverable genuinely is
software. Each command runs to completion, so verify with a script that exits,
not by starting a server and hoping.

**ANALYSIS** — work on a dataset they uploaded. Profile it, compute, show the
result, say what it means.

**ANSWER** — a question to answer well. Research it where that helps; reach for
a visual only where it makes the answer clearer.

The test that resolves most cases: *is the thing they want the FILE, or the
EXPERIENCE?* "A game I can play" is an artifact. "A game I can put on GitHub" is
workspace software.

## Inside the artifact surface, which tool

| They want to… | Use | Not |
|---|---|---|
| move through or play with something in 3D | `create_3d_experience` | `render_custom` with Three.js by hand |
| see a 3D *chart* (surface, 3-variable scatter) | `generate_3d` | `create_3d_experience` |
| change a parameter and watch a result move | `create_simulation` | a static chart plus a paragraph |
| see how one quantity relates to another | `generate_visual` | a table of the same numbers |
| follow a process, order, or flow | `create_diagram` | prose with arrows in it |
| watch something built up step by step | `create_animation` | a diagram of the finished state |
| explore how many things relate | `create_knowledge_graph` | a bullet list of relationships |
| read a document, handout, or small tool | `create_html_page` | a wall of chat text |
| present to a room | `generate_deck` | a document with headings |
| something with no schema at all | `render_custom` | forcing it into one of the above |

If two fit, pick the one that makes the reader DO something. A chart they read
is worth less than a slider they drag, when the point is a relationship.

## Do not decorate

A visual that restates a sentence is worse than the sentence: it costs time to
produce, space to display, and attention to skip. Make one when it carries
something prose cannot — a shape, a comparison, a magnitude, a structure.

Three numbers are a sentence. Twenty numbers are a chart. A process is a
diagram. A relationship you want them to feel is a simulation.

## Changing your mind

If you decided wrongly, re-plan rather than working around it. Building the
wrong shape carefully is more expensive than starting the right one — and the
toolset you are given follows the surface you committed to, so working around it
means fighting the tray rather than picking a different instrument.

## Then commit

Say what you are making, in one line, before you make it. Not as a preamble to
the user — as the decision you are then held to. A turn that quietly becomes a
different deliverable half way through produces something nobody asked for.
