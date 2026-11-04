# Umay

Before reviewing code, read [docs/INDEX.md](docs/INDEX.md) and only the notes your task needs. Then open only
the files those notes name; don't read the whole codebase to get oriented. Every module starts with a
docstring that says what it does.

- Tests: `python -m unittest discover -s tests` (~25 s).
- A change reaches the running app only after build + deploy: [docs/workflow.md](docs/workflow.md).
- When your change makes a note in `docs/` wrong, fix that note in the same change.
