---
name: exam-paper-practice
title: Setting and marking practice questions the way the exam actually does
description: Building NECTA/CSEE-shaped practice from a syllabus topic, marking it against a real scheme, and turning the marks into what to study next.
tags: necta, csee, acsee, exam, practice, marking, students, revision, tanzania
---

A student who has read the notes and failed the paper does not have a knowledge
problem. They have a *format* problem: they do not know what the question is
asking them to produce, or how the marks are distributed inside it. Practice
only helps if it has the shape of the real thing.

This is about producing that shape, and marking against it honestly.

## Read the command word first

Marks are attached to the verb, not the topic. A student who explains when the
paper said *state* loses time; one who states when it said *explain* loses
marks.

| Command | What earns the mark |
|---|---|
| State / Name / List | The item itself. No justification wanted. One mark each, usually. |
| Define | The full defining property, in the standard wording. Near-misses fail. |
| Describe | What happens, in order. Sequence carries marks. |
| Explain | Cause and mechanism. *Because* is the word that earns it. |
| Distinguish / Compare | Both sides, on the SAME axis. One-sided answers score half. |
| Calculate / Determine | Method marks for working, one for the answer, one for the unit. |
| Discuss / Evaluate | Both directions plus a judgement. A one-sided answer caps out. |
| Draw / Sketch | Labelled, titled, and to the stated convention. |

Set questions using these verbs exactly, and put the mark allocation in brackets,
because that is how the student learns to budget time.

## Build the paper in the real proportions

Ask, or infer from the syllabus topic:

- **Which paper** — CSEE and ACSEE differ in depth and in the balance between
  structured and essay questions.
- **Section shape** — most papers run short objective/structured items first,
  then longer structured, then essays. Practice that ignores the ordering
  trains the wrong pacing.
- **Marks and minutes** — roughly one mark per minute is the usable rule.
  Include the timing, because running out of time is the most common way a
  student who knew the material still failed.

Draw the content from the actual syllabus topic, and where a figure or a local
context is needed, use a Tanzanian one — the real papers do, and a student who
has only practised on textbook examples from elsewhere reads the context as an
extra obstacle.

## Mark honestly, and show the scheme

Marking is the part with the value in it. Always give:

1. **The marking scheme, before the model answer.** What each mark is FOR.
2. **The mark you would award**, per part, with the reason.
3. **The exact words that would have earned the missing mark.** Not "you should
   have explained more" — the sentence.
4. **The total**, and what grade band that is.

Do not be generous. A student who is told they scored 8/10 for an answer a real
examiner would give 5 has been actively harmed: they will stop revising a topic
they have not learned. Being told 5, with the two sentences that would have made
it 8, is the whole point of practising.

## Then turn the marks into a plan

A score alone is a verdict. What the student needs is the next action:

- Which specific sub-topics lost marks, in priority order.
- Which losses were knowledge and which were format — those need different
  fixes, and format is much faster to repair.
- Two or three more questions on exactly the weak sub-topic, harder than the
  first.

Then hand it to `exam-revision` for the schedule, and use `remember` to record
what they got wrong, so the next chat in this project starts from their actual
weaknesses rather than from the syllabus again.

## What to produce

For a practice set: `create_html_page` gives them one file they can print, work
on paper, and mark themselves — which is closer to exam conditions than typing
into a chat, and works offline on a phone.

Keep the questions and the marking scheme in **separate sections**, with the
scheme after the questions, so the paper can be attempted before it is read.

## What not to do

- Do not write the answers into the question paper.
- Do not invent a past paper and present it as a real one. "In the style of
  CSEE" is honest; "2019 CSEE Paper 2" is a fabrication a student may cite.
- Do not soften a mark to be encouraging. Encourage in the words around the
  mark, not in the mark.
