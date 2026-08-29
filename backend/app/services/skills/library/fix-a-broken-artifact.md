---
name: fix-a-broken-artifact
title: Repairing something that rendered wrong, without breaking it differently
description: What to do when a chart, scene, page or diagram fails verification — read the real error, edit the smallest thing, and never start over.
tags: repair, debugging, artifact, verification, blank, broken, update_visual
---

Every artifact you produce is opened in a real browser before the user sees it.
When it fails, you are told so as a **failed tool call** with the specific
errors, and the artifact is withheld. You get **two repair attempts**. After
that it is released with its defects on the record and you must describe them
honestly.

This skill is about spending those two attempts well, because the obvious way to
spend them does not work.

## The rule: edit, do not regenerate

The instinct is to write the whole thing again with the problem fixed. Do not.

Re-emitting four hundred lines of scene code to fix a missing `return` produces
four hundred *different* lines. They have a new fault in them about as often as
the old ones did, so the second attempt fails for an unrelated reason, and the
user watches the same thing break twice in two different ways — which reads as
incompetence rather than as one small mistake.

Editing converges because everything that already worked stays byte-identical.

```
update_visual(visual_id="…", code="…the same code, with line 214 fixed…")
```

`update_visual` works on every kind of visual — 3D scenes, HTML pages, custom
visuals, diagrams, simulations, animations, graphs, charts. It keeps the same
id and URL, so a panel the user already has open updates in place instead of a
near-duplicate appearing beside it.

**If you cannot remember what you wrote, that is the strongest possible argument
for editing rather than rewriting.** The stored version is the real one.

## Read the actual error first

Do not guess from the symptom. The message names the cause.

| What you are told | What it means | The fix |
|---|---|---|
| "does not parse … around line N" | A SyntaxError. The browser abandons the whole script, so the page is blank. | Go to line N. It is almost always an unclosed bracket, brace or string, or a stray comma. Nothing else is wrong. |
| "finished without returning a BABYLON.Scene" | The scene was built and never returned. | Add `return scene;`. |
| "no active camera" / "rendered nothing" | Nothing was drawn, and nothing threw. | Check a camera and a light exist; check you drew into an element that is in the document. |
| "the chart rendered with no marks on it" | The Vega spec is valid and draws nothing. | A field name in `encoding` that is not in the data (check spelling AND case), an empty `data.values`, or a `transform` filter that excludes every row. |
| "diagram rendered with nothing in it" | Nodes were accepted, none laid out. | An edge's `from`/`to` does not match any node id exactly. |
| "script #N loads an external URL" | Artifacts have no network. | Inline it. Nothing is fetched at runtime, ever. |
| "imports X, which cannot be resolved" | There is no bundler and no module resolver. | Use the globals: `THREE`, `BABYLON`, `React`, `ReactFlow`, `d3`, `dagre`. |
| "the file may be truncated" | You stopped mid-generation. | Write it again in full — this is the one case where rewriting is right, because what is stored is genuinely incomplete. |

## Change one thing

If two things are reported, fix both — but as two specific edits, not as a
rewrite that happens to address both. When you are unsure which of two changes
matters, you have not diagnosed it yet; read the error again.

## When the budget runs out

The artifact is released anyway, and you must **say plainly and specifically
what does not work**. Not "there may be minor issues" — "the orbit controls do
not respond on touch; the geometry and lighting are correct."

A broken artifact with an accurate description of how it is broken is genuinely
useful: the user can decide whether it matters, and they can tell you something
you could not have known. A broken artifact described as finished costs them the
time it takes to discover the truth, and costs you the credibility that makes
everything else you say worth reading.

## What never helps

- Changing the title, the theme or the wording of your description. None of
  those are what failed.
- Switching to a different tool because this one "isn't working". A diagram that
  fails because an edge points at a missing node will fail the same way as a
  knowledge graph.
- Saying "this should work now" without resubmitting it. You have a browser;
  use it.
