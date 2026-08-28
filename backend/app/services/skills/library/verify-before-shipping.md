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
| any generated page or visual | `verify_artifact` | renders blank in the browser |
| a written file | `workspace_verify` | silently truncated |
| an analysis | re-read the output: counts, ranges, units, sign | wrong column, wrong units |
| a citation | `check_citation` | the source does not exist |
| a claim about local facts | is it in GROUNDING? | confabulated statistic |

## The loop

1. Produce it.
2. Check it.
3. **If the check fails: read the actual error, fix, check again.** Two or three
   rounds is normal engineering. It is not a sign anything has gone wrong.
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
