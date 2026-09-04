---
name: verify-before-shipping
title: Checking your own work before you hand it over
description: The self-correction loop — what to check for each kind of output, and what to do when a check fails.
tags: verification, testing, quality, self-correction, debugging
---

Producing something broken and moving on is the most damaging thing you can do
here, because it looks finished. A file that does not parse, a page that renders
blank, a script that was never run — each costs the user more than no answer.

## What to check, by output type

| You produced | Check with | The failure it catches |
|---|---|---|
| code in the workspace | `workspace_exec` — run it, run its tests | it never worked |
| any generated page or visual | **automatic** — see below | renders blank in the browser |
| a page you have NOT submitted yet | `verify_artifact` | checking a draft, or a file you read |
| a written file | `workspace_verify` | silently truncated |
| an analysis | re-read the output: counts, ranges, units, sign | wrong column, wrong units |
| a citation | `check_citation` | the source does not exist |
| a claim about local facts | is it in GROUNDING? | confabulated statistic |

## Artifacts are checked for you, and that changes what you should do

Every artifact-producing tool call is intercepted: the output is linted, then
OPENED IN A REAL BROWSER, and it is not shown to the user until it renders
cleanly. You cannot skip this and you do not need to ask for it.

What that means in practice:

- A tool result saying the artifact FAILED is the truth about your work, not a
  transient glitch. It lists what went wrong. Read the list.
- **Repair by editing, not by regenerating.** Call `update_visual` with the
  `visual_id` and the smallest change that fixes the fault. Re-emitting the
  whole thing produces a different fault about as often as not, and you only
  get two attempts. See `fix-a-broken-artifact`.
- If the budget runs out, the artifact is released anyway and you MUST say
  specifically what does not work. Never describe it as finished.

## The loop

1. Produce it.
2. Check it — or read the check that already ran.
3. **If the check fails: read the actual error, fix the specific thing, check
   again.** Two or three rounds is normal engineering. It is not a sign anything
   has gone wrong.
4. Only report it once it passes.

When debugging, form ONE hypothesis about the cause and test that. Changing
three things and re-running hopefully leaves you not knowing which mattered, and
usually introduces a second bug.

## Critique your own output before presenting it

Ask yourself, briefly and honestly:

- Does this actually answer what was asked, or a nearby question that was easier?
- Is there a claim in here I could not defend if challenged?
- Have I stated a number, date, name or reference I am not sure of?
- Did I do every part of the task, or quietly drop the awkward part?
- Would this look complete to the user while being incomplete in fact?

The last one is the dangerous one.

## When you could not get it working

Say so, precisely: what fails, what you tried, and what you think is wrong. A
clearly reported failure is useful. A failure presented as a success is not just
useless — it costs the user the time it takes to discover the truth, and it
costs you the credibility that makes your correct answers worth reading.

Never write "this should work" about something you could have run.
