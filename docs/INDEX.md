---
title: Umay project notes
date: 2026-11-05
tags: [umay, index, agents]
aliases: [Umay memory, project memory]
---

# Umay project notes

The project's memory for developers and Claude Code sessions. The aim is that a session does not have to
re-read 28,000 lines of code to find its way. Start here, open only the note your task needs, then read only
the files that note names. [README.md](../README.md) is the user manual (features, setup, settings). These
notes cover what the README does not: how the code fits together and the traps found so far.

Verified against the code on 2026-11-05 (86 modules, 636 unit tests). [CLAUDE.md](../CLAUDE.md) at the
project root points every Claude Code session here.

## Notes

- [Architecture](architecture.md): read first on any non-trivial task. Covers processes, threads, startup
  order, the message path from input to model to tools, and the separate Python envs.
- [Module map](module-map.md): which file owns what, grouped by area, with sizes. Use it to find the 2-3
  files a task touches instead of grepping everything.
- [Tools and confirmations](adding-a-tool.md): read before adding or changing a tool the model can call, a
  shortcut that skips the model, or anything that asks the owner yes/no.
- [Workflow](workflow.md): how to run the tests, build the exe, deploy it to the running app, and keep the
  development plan (`development/planned.txt`, `done.txt`).
- [Pitfalls](pitfalls.md): read before editing. These are mistakes that already cost hours: Tk threads,
  PyInstaller env vars, heredoc patches, live window tests.

## Keeping these notes true

These notes only save tokens while they are right. When a change makes a note wrong (a new module, a moved
responsibility, a new trap), fix the note in the same change. Don't add a note for something the code or
the README already says clearly.

Related: [README.md](../README.md), [development/planned.txt](../development/planned.txt)
