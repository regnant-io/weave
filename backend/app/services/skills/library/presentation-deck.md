---
name: presentation-deck
title: Building a deck someone can actually stand up and present
description: Slide-level structure, layout variety, how much text is too much, and the difference between a deck and a document with headings.
tags: deck, slides, presentation, defence, seminar, viva, teaching
---

A deck is not a document with headings. It is a sequence of things a person
SAYS, with something on screen that helps them say it. Every failure mode here
comes from forgetting that: the slide that is a paragraph, the deck where all
twenty slides have the same shape, the bullet list nobody in the room can read
from the back.

Use `generate_deck` when the deliverable is presented to a room — a proposal
defence, a seminar, a class, a conference talk. Use `create_html_page` when it
is read alone.

## Structure first, slides second

Write the spine before any slide exists. For a research presentation:

1. The question, and why anyone should care.
2. What is already known — briefly, and only the parts your work touches.
3. The gap.
4. What you did.
5. What you found. *This is the middle of the deck and gets the most slides.*
6. What it means, and what it does not mean.
7. Limitations, stated by you before they are asked.
8. What next.

For a 15-minute slot that is 12–15 slides. Someone who has 40 has not decided
what the talk is about.

## Vary the layout, deliberately

A deck where every slide is a heading plus bullets is the clearest possible
signal that nobody designed it. Change shape at least every third slide.

| Layout | Use it for |
|---|---|
| `title` | Opening. Title plus one line saying what this is. |
| `section` | A numbered divider. Gives the room a moment to reset. |
| `statement` | One short, strong idea, set large. The finding. The claim. |
| `bullets` | A heading and 3–5 short points. Never more than five. |
| `split` | Two columns — before/after, method/result, ours/theirs. |
| `quote` | A quotation, with the attribution in `title`. |
| `data` | Up to four headline figures with labels. Your results slide. |
| `end` | Close. Not "Thank you" — the one sentence you want remembered. |

The `data` layout is underused and it is the best one you have for a results
section: four numbers, large, with their labels, beats a table nobody can read.

## How much text

Under about 40 words in a body. If a slide needs more, it is two slides, or it
is a sentence the presenter says out loud while a single figure sits on screen.

Bullets are fragments, not sentences. "Yields up 23% under irrigation" — not
"Our analysis found that yields increased by 23 percent among the farms that had
adopted irrigation."

Never paste a paragraph onto a slide. The audience will read it, at their own
speed, and stop listening to the person talking.

## Say the number, then say what it means

A results slide that shows `p = 0.03` and stops has told the room nothing they
can use. Pair every figure with its consequence:

> **23%** — higher yield under irrigation
> *enough to cover the pump within two seasons*

The second line is the one people remember, and it is the one that gets left out.

## Bilingual decks

Both languages work. Pick one for the deck and stay in it — a deck that switches
between slides is harder to follow than either language alone. Technical terms
that have no settled Kiswahili form should appear in English with a short gloss
the first time, not translated into something the audience has never heard.

## Finish

`format: "pdf"` also exports a PDF when Gotenberg is available; the HTML deck
prints to a real landscape PDF from any browser regardless.

Then tell them what to say. A one-line speaker note per slide — the sentence
that slide exists to support — is worth more than another slide.
