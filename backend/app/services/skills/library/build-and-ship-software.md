---
name: build-and-ship-software
title: Building software in the project workspace and actually shipping it
description: The engineering loop for the persistent workspace — explore, plan, build in small verified steps, test, package.
tags: code, workspace, engineering, testing, build, software
---

The project workspace is a real persistent directory with a container behind it:
Node 20, Python 3, git, ffmpeg, ImageMagick, and network access so you can
install dependencies. Treat it like a machine you are responsible for, not a
scratchpad.

## 1. Look before you build

`workspace_list` first, every time you return to a project. The single most
common failure is recreating something that already exists under a slightly
different name, leaving the user with two half-finished versions.

`workspace_read` any file you are about to change. You cannot write a correct
`find` string for `workspace_edit` from memory.

## 2. Say the plan in one short paragraph

Files you will create, the approach, and the single riskiest assumption. Then
build. Do not produce a twelve-point plan for a task with three steps.

## 3. Build in verified increments

Small steps that each end in a working state beat one large step that ends in a
pile of files that have never run.

- `workspace_edit` for changes to existing files. Rewriting a whole file for a
  one-line change is how you end up with a truncated version of the file that
  mattered.
- `workspace_write` for new files, **complete**. Never `...`, never
  "rest unchanged". A truncated file looks perfectly fine until it is opened.
- `workspace_verify` after anything substantial.
- `workspace_exec` to install, build and **run it**. A feature you have not
  executed is a guess.

## 4. Write and run the tests

Write the test that would have caught the bug. Then run it and show the output.
Reporting "the tests pass" without a run is the exact failure this product can
least afford — it produces broken work that looks finished.

When something fails: read the actual error, form one hypothesis, test that
hypothesis. Do not change three things at once and re-run hopefully.

## 5. Structure it like a project someone else will open

```
src/        the code
tests/      the tests
assets/     data, images
README.md   what it is, how to run it, what it needs
```
plus a real manifest (`package.json`, `requirements.txt`, `pyproject.toml`)
pinned to versions you actually installed.

Prefer a few well-structured files to many small ones. Keep the dependency list
short — every package is something that must install on the user's machine too.

## 6. Package and explain

`workspace_package` when it builds and passes, so the user gets a tarball.

Then say, in prose: what you built, how to run it, what you verified, and what
you did NOT do. If a test still fails, say which and why — do not present
partial work as complete.
