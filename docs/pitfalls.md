---
title: Pitfalls
date: 2026-11-05
tags: [umay, pitfalls]
---

# Pitfalls

Each of these already broke something. The date says when.

| Trap | What happened | Do this |
|---|---|---|
| Python patches through a Bash heredoc | `\n` became a real newline, `\b` became `\x08` (2026-11-02, twice on 11-03), even with `<<'EOF'` | Use Edit, or write the patch script with Write. Afterwards scan edited `.py` files for `chr(8)` |
| `_PYI_*` env vars | A Umay started by a session Umay launched reused the old `_MEI` folder and ran the old build three times (2026-11-04) | Remove `_PYI_*` before starting it. `paths.take_bootloader_env()` strips them inside Umay since then |
| Build in the PowerShell tool | stderr INFO lines turn into a NativeCommandError | Build from Bash ([Workflow](workflow.md)) |
| New worker / data file | PyInstaller only bundles imports. A file run as a script by another Python is missing in the exe | Add `--add-data "<file>;."` to `build.ps1`, like the existing workers |
| `root.after` across Tk threads | Two Tk threads waiting on each other froze the app (2026-10-21) | `tkpost.Mailbox.post` |
| Live window tests | A test found the owner's Notepad by class, moved it and closed it (2026-11-03) | Act only on a window the test made (a unique title or its pid). Never use Notepad |
| Tests touching real state | Calling `voice_guard.apply` / Ollama wrote to the real logs under `%LOCALAPPDATA%\Umay` | Mock `_log` and the paths |
| `i18n.py` is gitignored | Only `i18n.example.py` is pushed | Change both |
| Editing `personality.md` | It is also the owner's Telegram persona for Claude (loaded from the global CLAUDE.md) | Put app-only speaking rules in `ai_assistant.STYLE` |
| Two Claude sessions for one Telegram task | Both edited `planned.txt` and both messaged Telegram (2026-11-04) | On tasks from Umay, check `ListAgents` and `%LOCALAPPDATA%\Umay\claude_tasks` first |
| Turning on router layer 1 | The owner wants no sudden mistakes | Only after the review with the owner (set for 2026-11-12). Layer-1 tools must run through `ai_assistant`'s tool path so confirmations stay |
| Small local model (qwen3.5:4b) | It answered Turkish in broken Turkish and missed tools | Language rule goes last in the prompt. Commands it misses become rule-based shortcuts |

Related: [Workflow](workflow.md), [Architecture](architecture.md), [Tools and confirmations](adding-a-tool.md)
