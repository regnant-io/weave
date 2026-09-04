---
name: using-weave-well
title: Getting the most out of Weave's own capabilities
description: A map of what this product can actually do — the two sandboxes, delegation, memory, retrieval, rendering — and how they combine on a real task.
tags: weave, capabilities, tools, overview, orientation, workspace, memory, delegate
---

Read this when you are not sure what is available to you, or when a task feels
bigger than one tool.

## What you actually have

**Two separate sandboxes, for different jobs.**
- The **analysis sandbox** (`run_analysis`) is locked down: no network, no
  filesystem. Read data only with `weave_io.load_dataset()`, write outputs only
  with `weave_io.save_output()`. Use it for statistics on an uploaded dataset.
- The **project workspace** (`workspace_*`) is a real persistent container with
  Node, Python, git, ffmpeg and **network access**. Use it to build software,
  install packages, process files, and run things. It survives across chats.

**Retrieval, in layers.** `search_library` for the local Tanzanian academic
corpus — try it first for anything about Tanzania. `web_search` for the open web.
`deep_research` when the question needs several sources reconciled.
`check_citation` before relying on a reference.

**Delegation.** `delegate` hands one self-contained lookup to a worker that
reads the sources and reports back a short answer, so the sources never enter
this conversation. Several delegates run at once. Use it when you will read far
more than you will quote — see `delegate-and-parallelise`.

**Rendering.** Charts, diagrams, animations, interactive simulations, knowledge
graphs, Babylon scenes, decks and complete HTML pages, all rendered inline as
you go. Which one to reach for is a real decision — see
`choose-the-right-output`.

**Memory across time.** A project holds many chats. `remember` writes a fact
that outlives this conversation; `recall` retrieves one. This is what lets a
dissertation project run for months without starting over each week.

**Asking.** `ask_user` when a fork genuinely changes the work. Not for
permission.

## Things about this environment that change how you work

**Verification is not optional and not yours to skip.** Everything you render is
opened in a real browser before the user sees it. A broken artifact comes back
to you as a FAILED tool call with the specific errors, and it is withheld until
it works or the repair budget runs out. Plan on that check rather than being
surprised by it — and when it fails, repair by EDITING (`update_visual`), never
by regenerating. See `fix-a-broken-artifact`.

**Artifacts run with no network at all.** No CDN, no web font, no remote image,
no fetch. `THREE`, `BABYLON`, `React`, `ReactFlow`, `d3` and `dagre` are already
inlined as globals. Build geometry and colour in code, or download an asset into
the workspace first and pass it inline.

**Independent reads run concurrently.** Ask for three searches in one go rather
than one at a time; anything that changes something still runs in order.

**A long turn is safe to start.** The work is not tied to the user's connection
— a dropped network or a page refresh reattaches to the same run rather than
killing it. So a job that takes twenty minutes is a reasonable thing to begin,
provided you say so first.

**Each workspace command runs to completion.** A server started with
`workspace_exec` will just hit the timeout. Verify with a script that exits.

## Combining them — a worked shape

> "Help me understand whether irrigation improved yields in my district."

1. `list_skills` → read `data-analysis-workflow` and `statistical-test-choice`.
2. `search_library` for local studies and national statistics. If several
   districts or several papers need comparing, send them as parallel
   `delegate` calls rather than reading everything yourself.
3. Profile their uploaded dataset. Report what is actually in it before
   promising anything.
4. Clean it, stating each decision. Run the analysis. Check the output.
5. Chart the distribution, not just the means. If the point is how the effect
   varies with a parameter, make it a simulation instead.
6. `create_knowledge_graph` if the literature is contested enough to map.
7. `remember` the dataset's quirks, the method chosen, and why — the next chat
   in this project starts from there.
8. Interpret, with the caveats.

## Habits that make the difference

- `workspace_list` before building, so you extend rather than duplicate.
- Read a skill before following it. The name is not the procedure.
- Create the visual when it is useful, not at the end.
- Set `note` on every tool call — it is the step title the user watches.
- `update_plan` as each step genuinely finishes. A step is done when the thing
  RAN, not when it was written.
- Say what you assumed, and what you are unsure of.

## What you cannot do

Artifacts have no network at runtime. The analysis sandbox has no filesystem.
Delegates can only read. You cannot see the user's screen unless they share it,
and you cannot access anything outside this project. When something is genuinely
out of reach, say so plainly and offer the nearest thing you CAN do — but check
first that it really is out of reach, rather than assuming.
