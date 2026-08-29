---
name: interactive-simulation
title: Building a simulation the learner actually manipulates
description: How to design a create_simulation spec that teaches — choosing the mode, the parameters worth exposing, the window, and the readouts that make the point land.
tags: simulation, teaching, sliders, physics, model, interactive, parameters
---

`create_simulation` is the strongest teaching tool here, and the most often
skipped. Reach for it whenever understanding depends on seeing how an outcome
RESPONDS to a change: projectile angle, interest rate, sample size, dosage,
population growth, a confidence interval as n grows.

A static chart shows one case. A simulation shows the *relationship*, which is
what the student was actually failing to see.

## Pick the mode from the phenomenon

- **plot** — a curve over an independent variable. The default. "How does y
  depend on x, and what happens to that dependence when I change a?"
- **motion** — bodies moving over time. Trajectories, orbits, collisions,
  anything where the answer is a path.
- **field** — a vector field over x and y. Flow, gradients, forces.
- **bar** — a handful of categories that respond to the parameters. Budget
  splits, allocations, comparisons.

If you find yourself wanting two modes, you want two simulations. One that tries
to be both teaches neither.

## Expose the parameters that carry the insight

Every parameter becomes a slider, and every slider is a claim that this quantity
is worth thinking about. Three or four is usually right. Eight is a control
panel nobody touches.

For each: sensible `min`/`max` (the range where something interesting actually
happens, not the mathematically valid range), a `value` that starts somewhere
illustrative rather than at zero, a `unit` when it has one, and a `label` a
student would recognise from their own course.

The test: **can they break it?** A parameter range that only produces sensible
answers teaches less than one where pushing the slider too far visibly ruins the
outcome. That is where the understanding is.

## Formulas are a small language, on purpose

Strings, evaluated in a restricted maths language over the parameters plus the
independent variable (and `t` in motion mode).

Available: `+ - * / ^ %`, comparisons, ternary `a ? b : c`, and `sin cos tan
asin acos atan atan2 sinh cosh tanh exp log ln log10 log2 sqrt abs min max pow
floor ceil round sign clamp lerp step mod hypot gauss`, with constants `pi`,
`e`, `tau`.

Nothing else — no assignment, no loops, no arbitrary JavaScript. If the model
genuinely needs more than this, it is not a simulation spec; use
`render_custom` and write it properly.

```
y: "v0 * sin(theta * pi / 180) * t - 0.5 * g * t^2"
```

Write the formula the way the textbook writes it. A student who cannot match
your expression to their notes cannot check your work.

## Set the window deliberately

`view: {xmin, xmax, ymin, ymax}`. Auto-scaling is the single most common way a
correct simulation becomes useless: the curve rescales as the slider moves, so
everything always looks the same and the change is invisible. Fix the window to
the range that makes the change legible, and let the curve leave it.

## Readouts do the teaching

`readouts: [{label, expr, unit}]` show live computed values. This is where the
learning happens: "range: 47.3 m" changing as the angle slider moves connects
the picture to the number.

Pick the two or three quantities the student is actually being examined on —
maximum height, time of flight, doubling period, the p-value — not whatever is
easiest to compute.

## Then say what to try

A simulation handed over without instructions is a toy. Finish with one or two
concrete invitations: *"Set the angle to 45° and vary the initial speed — notice
the range grows with the square. Now hold the speed and sweep the angle; find
where it peaks and ask yourself why it is not 60°."*

That last clause is the difference between a demonstration and a lesson.

## If it comes back broken

The renderer rejects an invalid expression by name, which tells you exactly
which formula to fix. Fix that formula with `update_visual` — do not rebuild the
whole spec. See `fix-a-broken-artifact`.
