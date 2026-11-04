---
title: Workflow
date: 2026-11-05
tags: [umay, tests, build, deploy]
---

# Workflow

## Tests

```bash
python -m unittest discover -s tests          # from the project folder: 636 tests, ~25 s, all pass (2026-11-05)
python -m unittest tests.test_router          # one module
```

The lines `Disk: Gemini didn't answer`, `Router: RuntimeError('broken')` and
`Tk mailbox: ZeroDivisionError` in the output are expected: tests print them on purpose. Run the module's
own test after a change, and the full suite before a build.

## Build and deploy (a change is live only after this)

The running app is `%USERPROFILE%\Documents\Apps\Umay\Umay.exe`, with its own `.env`, `config.json` and
`chat_logs`. It is a copy of `dist\Umay.exe`.

1. Build from **Bash**, in the background (~4 min):
   `powershell.exe -NoProfile -ExecutionPolicy Bypass -File build.ps1 > <scratch>/build.log 2>&1`.
   Don't use the PowerShell tool: PyInstaller's stderr turns into a NativeCommandError and the build dies.
2. Stop the running Umay, copy `dist\Umay.exe` over the one in `Apps\Umay`, start it again. Stop the old one
   first: a second Umay quits at once (mutex).
3. Start it without the `_PYI_*` env vars (`Remove-Item Env:_PYI_* -ErrorAction SilentlyContinue` before
   `Start-Process`). See [Pitfalls](pitfalls.md).

While Umay restarts, a `/ss` or similar the owner sends to the shared bot can land in a pending claude_comm
`ask`. That message is not an answer.

## Development plan

`development/planned.txt` (to do) and `development/done.txt` (done) are in Turkish, with numbered items
that are unique across both files. Umay reads "item 8" through `calendar_tools.read_plan_item`. When an item
is finished, move it to `done.txt` with its number, the date, `BİTTİ` and one or two lines about what was
done. States: BEKLİYOR, ÖNERİ, DEVAM EDİYOR, BİTTİ.

## Checking real behaviour

- Real tool replies: `%LOCALAPPDATA%\Umay\*.log` (spotify, calls, companion, memory...).
- Tool names per request: `credit_log.sqlite`, column `detail`.
- What the router would have done: `python router.py review [YYYY-MM-DD]`.

Related: [Pitfalls](pitfalls.md), [Architecture](architecture.md)
