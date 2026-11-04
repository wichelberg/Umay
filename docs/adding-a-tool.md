---
title: Tools and confirmations
date: 2026-11-05
tags: [umay, tools, safety]
---

# Tools and confirmations

## Adding a tool the model can call

1. In the owning module, add an OpenAI-style function schema to its `TOOLS` list and the callable to
   `TOOL_FUNCTIONS` (same name). Return a plain string the model can read. To show the model a picture,
   return `{"text": ..., "image": data_uri}` (or `"images": [...]`).
2. For a new module, add `module.TOOLS` and `**module.TOOL_FUNCTIONS` to the two lists in
   `ai_assistant.py` (around `TOOLS = [` and `TOOL_FUNCTIONS = {`).
3. Strings shown to the owner go in `i18n.py` **and** `i18n.example.py`, in `en` and `tr`.
4. If it is a research tool (reads the web/memory), add it to `RESEARCH_TOOLS`. If it acts on the screen,
   add it to `SCREEN_TOOLS`.
5. If the small model keeps calling it wrong, add a rule-based shortcut (`module.asked(text)`) at the top of
   `_send_message` instead of making the description longer. That is the existing pattern.
6. Router: if the tool belongs to a category in `router.CATEGORIES`, add it there too. Layer-1 tools must be
   reversible or ask first: never delete, send, or return results the model has to interpret.
7. Add `tests/test_<module>.py` (unittest, mock the PC; see [Pitfalls](pitfalls.md)).

## Confirmations: always through `pc_tools`

- `pc_tools.confirm(key, **kwargs)` asks before anything that changes the PC. Where it asks depends on the
  thread's channel. From the PC it asks aloud (`voice_confirm`), then the yes/no box if voice can't run.
  From Telegram it uses buttons (`pc_tools.channel(...)` set by `telegram_listener`). In sleep mode the
  answer is always yes.
- `pc_tools.ask_everywhere` is for the "ask before every step, reading included" tools (web control,
  reading WhatsApp). Since 2026-11-02 it asks only where the request came from, never as text on screen.
- A declined action returns `pc_tools._declined()` ("don't retry unless they ask again").
- Background jobs report back with `pc_tools.current_notifier()`. Photos go to Telegram with
  `current_photo_sender()`.
- Errors: raise `ToolError` and wrap the body in `_run(...)`, so the model gets a sentence, not a traceback.

## Safety rules the code enforces (keep them)

- File paths: `pc_tools._resolve` keeps everything inside `UMAY_ALLOWED_DIRS`, and paths must be absolute.
- Sending files: `_shareable_file` refuses secrets (`SECRET_NAMES`, `SECRET_FOLDERS`, including the
  claude_comm folder).
- Ending processes never touches Windows, security software, other users or Umay herself.
- Health escalation and sleep mode are the only actions taken without asking. See README "Safety".

Related: [Architecture](architecture.md), [Module map](module-map.md), [Pitfalls](pitfalls.md)
