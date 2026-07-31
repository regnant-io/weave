---
name: single-file-html
title: Building a big, beautiful, responsive single-file HTML artifact
description: How to write one complete self-contained HTML page that works offline, reads well on a phone, and does not render blank.
tags: html, artifact, responsive, document, offline, css
---

Use `create_html_page` when the deliverable is a DOCUMENT rather than a chart: a
revision sheet, an interactive explainer, a marking rubric, a small calculator, a
report. One complete page, written in one string.

## The hard constraints — these are not style advice

The page runs in an opaque-origin iframe under a strict CSP with **no network**.

- No CDN scripts. No `<link>` to a stylesheet. No web fonts. No remote images.
- No `fetch`, `XMLHttpRequest`, `WebSocket`, `localStorage`.
- **No `import` statements.** There is no bundler and no module resolver. Write
  plain browser JavaScript. The libraries the service inlines are already
  globals (`THREE`, `BABYLON`, `React`, `ReactFlow`, `dagre`).
- Inline everything: data as JS literals, images as `data:` URIs, all CSS in one
  `<style>` block.

Violating any of these does not degrade the page — it blanks it.

## Structure that works

```
<!doctype html><html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>…</title>
<style> /* tokens, then layout, then components */ </style>
</head><body>
  <header>…</header>
  <main>…</main>
  <footer>…</footer>
<script> /* plain JS, no imports */ </script>
</body></html>
```

Define colour and spacing as CSS custom properties at `:root` first, then use
them everywhere. That single habit is most of what makes a page look designed.

## Typography

Match Weave: one grotesque for everything, one monospace for labels, figures and
code. Because there is no network, use system stacks:

```css
--sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Inter, Roboto, sans-serif;
--mono: ui-monospace, "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace;
```

Body text 16–17px, line-height ~1.6, measure capped at `65ch`. Headings get
weight and tight tracking (`-0.02em`), not a different family.

## Responsive, and mobile-first

Most Weave users are on a phone on a slow connection.

- Start with the single-column layout and add columns at breakpoints, not the
  reverse.
- Every wide thing — tables, code blocks, diagrams — goes in its own
  `overflow-x: auto` container. The page body must never scroll sideways.
- Tap targets ≥ 44px. Inputs at `font-size: 16px` or iOS zooms on focus.
- Support both themes with `@media (prefers-color-scheme: dark)`.
- `@media print` if the page is something a student would sensibly print — for a
  revision sheet, they will.

## Interactivity

Keep it real but small: collapsible sections, a filter box, a self-marking quiz,
a calculator. Use `<details>`/`<summary>` before writing JavaScript. Respect
`@media (prefers-reduced-motion: reduce)`.

## Then verify

Call `verify_artifact` on the page before you tell the user it is ready. It
catches ESM syntax in a classic script, external resources, and truncation — the
three failures that look fine in the source and blank in the browser. If it
fails, fix and re-check. Do not hand over a page you have not verified.
