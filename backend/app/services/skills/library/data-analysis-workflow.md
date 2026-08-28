---
name: data-analysis-workflow
title: Taking a messy dataset through to a defensible result
description: The full path from an uploaded file to a result you can stand behind — profile, clean, decide, test, visualise, report the caveats.
tags: data, analysis, cleaning, statistics, pandas, dataset, research
---

Never run a test on a dataset you have not looked at. Most wrong answers in
student and research analysis come from step 1, not step 4.

## 1. Profile before anything else

Load with `weave_io.load_dataset()` and report, in prose:

- rows and columns; what one row actually represents (a person? a household? a
  household-year?)
- per column: dtype, missing count, unique count, min/max for numerics
- the top few values of every categorical column

Then say what you noticed. Missingness that is not random, a "999" sentinel, a
column that is numeric but stored as text, dates in three formats, duplicated
IDs, a category with 47 spellings — these are the findings that change the
analysis, and they are invisible in a summary table alone.

## 2. Clean, and record every decision

Every cleaning step is a judgement the reader must be able to audit.

- Sentinels (`-99`, `999`, `N/A`, empty string) → real NaN.
- Trim and case-normalise categorical text before grouping, or you will count
  `Dar es Salaam`, `dar es salaam` and `Dar-es-Salaam` as three regions.
- Parse dates explicitly. Never rely on inference for `03/04/2022`.
- Duplicates: decide whether they are true duplicates or repeated measures, and
  say which.
- Outliers: **investigate, do not delete**. An impossible value (age 350) is a
  data-entry error; an extreme but possible value is data. Deleting the second
  kind is how findings get manufactured.

State the row count after each step. If cleaning dropped 40% of the data, that
is the headline, not a footnote.

## 3. Choose the analysis deliberately

Match the question to the method, and check the assumptions before you report
the result. If unsure, read the `statistical-test-choice` skill.

State the unit of analysis and the population you are generalising to. A
convenience sample of one school does not speak for a region, and saying so is
part of the answer.

## 4. Run it, then check it

- Run the analysis with `run_analysis`.
- Sanity-check the output: do the group sizes add up? Is the effect in a
  plausible direction and magnitude? Are the units what you expect?
- Report effect sizes and confidence intervals, not just p-values. "p < 0.05"
  with an effect size of 0.02 is a large sample, not a finding.

## 5. Visualise the actual distribution

Show the data, not only the summary. A box or strip plot beside the means is
what reveals that a "significant difference" is two overlapping clouds. Follow
the `beautiful-visualisation` skill for form and palette.

## 6. Report honestly

Close with what would change the conclusion: the sample's limits, the
assumptions that were shaky, the confounder you could not control for, the
missingness you had to impute. A result presented without its caveats is not
more convincing — it is just less useful.
