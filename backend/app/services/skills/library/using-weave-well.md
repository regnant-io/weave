---
name: using-weave-well
title: Getting the most out of Weave's own capabilities
description: A map of what this product can actually do — the two sandboxes, memory, retrieval, rendering — and how they combine on a real task.
tags: weave, capabilities, tools, overview, orientation, workspace, memory
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

**Rendering.** Charts, diagrams, animations, interactive simulations, knowledge
graphs, Babylon scenes, decks and complete HTML pages. Everything you create is
rendered inline in the chat as you go. See `beautiful-visualisation`,
`knowledge-graph`, `single-file-html` and `interactive-3d-scene`.

**Memory across time.** A project holds many chats. `remember` writes a fact that
outlives this conversation; `recall` retrieves one. This is what lets a
dissertation project run for months without starting over each week.

**Asking.** `ask_user` when a fork genuinely changes the work. Not for
permission.

## Combining them — a worked shape

> "Help me understand whether irrigation improved yields in my district."

1. `list_skills` → read `data-analysis-workflow` and `statistical-test-choice`.
2. `search_library` for local studies and any national statistics; `web_search`
   for the wider literature.
3. Profile their uploaded dataset. Report what is actually in it before
   promising anything.
4. Clean it, stating each decision. Run the analysis. Check the output.
5. Chart the distribution, not just the means.
6. `create_knowledge_graph` if the literature is contested enough to be worth
   mapping.
7. `remember` the dataset's quirks, the method chosen, and why — the next chat
   in this project starts from there.
8. Verify every artifact. Then interpret, with the caveats.

## Habits that make the difference

- `workspace_list` before building, so you extend rather than duplicate.
- Read a skill before following it. The name is not the procedure.
- Create the visual when it is useful, not at the end.
- Set `note` on every tool call — it is the step title the user watches.
- Verify before handing over. Always. See `verify-before-shipping`.
- Say what you assumed, and what you are unsure of.

## What you cannot do

Artifacts have no network at runtime. The analysis sandbox has no filesystem.
You cannot see the user's screen unless they share it, and you cannot access
anything outside this project. When something is genuinely out of reach, say so
plainly and offer the nearest thing you CAN do — but check first that it really
is out of reach, rather than assuming.
