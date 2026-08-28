---
name: statistical-test-choice
title: Choosing, checking and reporting the right statistical test
description: A decision path from research question to test, the assumptions each one needs, and how to report the result without overclaiming.
tags: statistics, hypothesis, test, regression, anova, p-value, research
---

## Start from the question, not the software

Answer these three before choosing anything:

1. **What is the outcome?** Continuous, binary, count, ordinal, time-to-event?
2. **What is the predictor?** One group, two groups, several groups, a
   continuous variable, several variables?
3. **Are observations independent?** Repeated measures on the same person,
   pupils within schools, and measurements over time are **not** independent,
   and a test that assumes they are will give a confidently wrong answer.

## The decision path

**Continuous outcome**
- One group vs a known value → one-sample t-test
- Two independent groups → independent t-test (Welch's by default — do not
  pre-test for equal variance, just use Welch)
- Two paired measurements → paired t-test
- 3+ independent groups → one-way ANOVA, then a corrected post-hoc (Tukey)
- 3+ paired → repeated-measures ANOVA or a mixed model
- Continuous predictor → linear regression
- Several predictors → multiple linear regression
- Clustered/nested data → mixed-effects model. Not a plain regression.

**Binary outcome**
- Two categorical variables → chi-square test of independence (Fisher's exact if
  any expected cell count < 5)
- One or more predictors → logistic regression

**Count outcome** → Poisson regression; negative binomial if variance ≫ mean.

**Ordinal outcome** (Likert) → do not average it as if it were continuous
without saying so. Mann-Whitney / Kruskal-Wallis, or ordinal logistic.

**Non-normal, small n** → the rank-based equivalent: Mann-Whitney for the
independent t-test, Wilcoxon signed-rank for the paired, Kruskal-Wallis for
one-way ANOVA.

## Check the assumptions — and say that you did

- **Independence** — from the study design, not from the data. This is the one
  that cannot be fixed after the fact.
- **Normality** — of the *residuals*, not the raw outcome. Look at a Q-Q plot.
  With n > 30 per group the CLT does most of the work; do not reach for a
  non-parametric test purely because a Shapiro-Wilk was significant on n = 2000.
- **Equal variance** — use Welch and stop worrying about it.
- **Linearity** — plot residuals against fitted values before trusting a
  regression coefficient.
- **Multicollinearity** — check VIF when predictors are related.

## Report it properly

Give: the test, the statistic with degrees of freedom, the p-value, **the effect
size, and a confidence interval**.

> Welch's t(47.3) = 2.81, p = 0.007, mean difference 4.2 marks
> (95% CI 1.2 to 7.2), Cohen's d = 0.71.

- p > 0.05 means "this study did not detect an effect", **never** "there is no
  effect". Absence of evidence is not evidence of absence.
- Testing many outcomes inflates false positives. Say how many tests you ran and
  correct for it (Holm or Benjamini-Hochberg) or state that you did not.
- A significant result from an observational study is an association.
  Say "associated with", not "causes", unless the design supports causation.
- Never report a p-value alone. It answers a question almost nobody is asking.
