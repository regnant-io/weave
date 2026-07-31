---
name: exam-revision
title: Building a revision plan and materials that actually work
description: Turning a syllabus and a deadline into a spaced, active-recall revision plan with materials the student will really use.
tags: study, revision, exam, necta, csee, students, learning, plan
---

Most revision fails for two reasons: the student re-reads notes (which feels
productive and teaches almost nothing), and the plan ignores how much time
actually exists. Fix both.

## 1. Establish the real constraints first

Ask, or infer from what you are told: which exam and level (CSEE, ACSEE, a
university course), which subjects, how many days until the paper, and how many
hours per day are genuinely available. A plan built on 6 hours a day for a
student who has 2 is worse than no plan.

Then get the syllabus topics. Use `search_library` for the NECTA syllabus and
past papers where relevant.

## 2. Rank topics by (weight × weakness)

Not by what is most interesting, and not in syllabus order. A topic that carries
20% of the marks and that the student cannot do is worth ten times one they have
already mastered. Ask them to rate their own confidence per topic — it is
usually roughly right and takes two minutes.

## 3. Build the schedule around retrieval, not review

- **Active recall**: the student answers from memory, then checks. Every
  session. Re-reading is not revision.
- **Spaced repetition**: each topic appears three times, at widening intervals
  (day 1, day 3, day 8). Put the second and third passes in the plan explicitly.
- **Interleaving**: mix topics within a session rather than blocking one topic
  for three hours. It feels harder and works better.
- **Past papers under timed conditions** in the final third. This is the single
  highest-value activity for a NECTA paper, because it trains the format as well
  as the content.
- Sessions of 25–45 minutes with real breaks. Include rest days; a plan with no
  slack is abandoned on the first day it slips.

## 4. Produce materials they will actually use

Build, do not describe:

- A **single-file HTML revision sheet** (`create_html_page`, see the
  `single-file-html` skill) with collapsible answers so it works as a self-test,
  and a print stylesheet — many students will print it.
- **A simulation** (`create_simulation`) for anything where understanding
  depends on how an outcome responds to a parameter: projectile angle, titration
  curves, compound interest, population growth. This is the highest-value
  teaching tool available and the most under-used.
- **A knowledge graph** for a topic map, so they can see how the syllabus
  connects.
- Worked examples that show the reasoning, then a parallel unworked question.

## 5. Teach the marking, not just the content

For NECTA papers especially: how marks are allocated, what a "state" vs
"explain" vs "discuss" command word requires, and where marks are commonly lost
(no units, no working shown, answering a different question).

## 6. Keep it honest

If the time available cannot cover the syllabus, say so and prioritise
explicitly: here is what we will cover, here is what we are consciously
dropping, here is the risk. A plan that quietly pretends there is enough time is
the one that collapses in week two.
