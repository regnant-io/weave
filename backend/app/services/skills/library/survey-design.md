---
name: survey-design
title: Designing a survey instrument that yields analysable data
description: Writing questions that measure what you intend, sampling and piloting it, and preparing the analysis before you collect anything.
tags: survey, questionnaire, sampling, fieldwork, likert, research, data collection
---

Every flaw in a questionnaire becomes permanent the moment collection starts.
Design against the analysis plan, not against the topic.

## 1. Write the analysis plan first

For each research question, write the exact table or test that will answer it,
then write the questions that produce those columns. If a question does not feed
a planned analysis, cut it — long instruments lower response quality on every
other question.

## 2. Question wording

- **One idea per question.** "Was the service fast and helpful?" cannot be
  answered by someone who found it fast and unhelpful.
- **No leading wording.** "How much did you benefit from…" presumes benefit.
- **No jargon, no negatives.** "Do you disagree that fees should not rise?" will
  be answered at random.
- **Concrete recall windows.** "In the last 7 days", not "usually".
- **Exhaustive, mutually exclusive options.** Age bands 18–24, 25–34 — not
  18–25, 25–35.
- Always offer "Don't know" and "Prefer not to say" where they are real. Forcing
  an answer manufactures data.
- Put sensitive questions (income, health, politics) late, after trust is built.

## 3. Scales

- Likert: use 5 points, label EVERY point (not just the ends), and keep the
  direction consistent throughout.
- Decide in advance whether you will treat it as ordinal or interval, and say
  which in the write-up. See `statistical-test-choice`.
- Reverse-code a few items to detect straight-lining, and remember to un-reverse
  them before analysis.

## 4. Translation

For bilingual fieldwork, translate to Kiswahili and **back-translate**
independently to English, then reconcile the differences. A question that means
something subtly different in the two languages produces two datasets, not one.
Pilot in the language of collection.

## 5. Sampling

State the sampling frame, the technique, and the sample size **with the
calculation shown**. Note who the frame excludes — a phone-based frame excludes
people without phones, which is very often the population of interest.

## 6. Pilot — this is not optional

Run it with 10–20 respondents. Time it. Find the questions people ask you to
repeat, the ones everyone answers identically, and the ones enumerators
paraphrase. Fix those, then collect.

## 7. Prepare for the data you will get

Define the codebook before collection: variable names, types, value labels,
missing codes. Decide now what "missing" means and how it will be coded, or you
will meet three conventions in one column.

Then, when the data arrives, follow the `data-analysis-workflow` skill — and
expect the messiness anyway.
