---
title: Architecture
date: 2026-11-05
tags: [umay, architecture]
---

# Architecture

## Processes

| Process | Python | Started by | Talks over |
|---|---|---|---|
| Umay (`main.py`, or `Umay.exe`) | Umay's own (3.12+) | the owner, or `shell:startup` | — |
| HUD (`main.py --hud` → `hud_app.py`, Qt) | Umay's own | `hud.start()` (restarted up to 3 times) | JSON lines on stdin/stdout: `{"event": name, ...}`, `hud.on(name)`, `hud.tell()` |
| Whisper STT (`speech_worker.py`) | `voice_env` | `voice.py` | worker pipe |
| TTS (`piper_worker.py` / `tts_worker.py`) | `piper_env` / `tts_env` | `voice.py` | worker pipe |
| RVC voice pack (`voice_worker.py`) | Wichelberg's Python | `voice.py` | worker pipe |
| Hands / camera (`hands_worker.py`) | `hands_env` | `eyes.py` | worker pipe |
| Face (`face_worker.py`) | `hands_env` | `face.py` | worker pipe |
| Local LLM | Ollama (`qwen3.5:4b`, 16k copy) | `local_llm.py` | HTTP, OpenAI-compatible |

The envs live under `%LOCALAPPDATA%\Umay\voice` (`paths.voice_home()`, `UMAY_VOICE_HOME`) and are made by
`setup_voice_env.py`. Workers are copied into the exe with `--add-data` (see [Pitfalls](pitfalls.md)).
Only one Umay runs: the named mutex `Local\Umay.instance` (`main.only_instance`).

## Startup (`main.main`)

Background threads: `_clean_mei` (old PyInstaller temp folders), `supervisor_loop` (alarm threads from
`config.json` via `check_event`), then `hud.start`, `telegram_listener.start`, `health_monitor.start`,
`voice_guard.start`, `voice_session`, `wake.start`, `web_control.start` (WebSocket for the Opera extension,
`127.0.0.1:47821`), `disk_watch.start`, `conversation_memory.start`, `companion.start`.

## Where a message goes

Every input ends up in `ai_assistant.answer_message(chat, text, language, source)`:

- Text box: `chat_box` → `ai_assistant._box_send` (source `box`)
- Telegram: `telegram_listener` wraps the call in `pc_tools.channel(confirm, notify, photo)` (source `telegram`)
- Voice: `voice_session` (source `voice`); WhatsApp call: `calls` (source `call`)
- Sleep mode: `sleep_mode` with a channel whose confirm is always yes

`answer_message` turns errors into i18n messages and records cost in `credit_log`. Then `_send_message`:

1. **Shortcuts with no model call**, in this order: `eyes.command`, `calls.asked`, `claude_terminal.asked`,
   `input_tools.asked`, `markets_follow.asked` / `news_follow.asked`, `spotify_tools.asked`. The 4b model got
   these wrong, so they are matched by rules.
2. **`router.route`**, SHADOW ONLY: it logs what layer 1 would have done to
   `%LOCALAPPDATA%\Umay\router_shadow.jsonl` and runs nothing. Layer 2 is off on purpose. Review with
   `python router.py review`. Don't turn layer 1 on without the owner's review.
3. **Tool loop**: up to `MAX_TOOL_ROUNDS` (40) requests. The tool calls run from `TOOL_FUNCTIONS`. Images
   returned by tools are sent as one user message; only the newest screenshot is kept. The HUD shows
   `research` for `RESEARCH_TOOLS` and `work` for the rest. When the context is too long, `_compact`
   summarizes the oldest turns.

The model is local Ollama unless `UMAY_LLM=openrouter` (`_provider` / `MODES` in `ai_assistant.py`). The
system prompt is [personality.md](../personality.md) + `TOOL_HINTS`. How she talks (`STYLE`) stays in
code, not in personality.md, because that file is also the owner's Telegram persona for Claude.

## Threads and UI

Several Tk roots run, each on its own thread: the text box, the alerts and the confirm box. Never call
`root.after` across Tk threads: use `tkpost.Mailbox.post` (two freezes on 2026-10-21 came from this). The HUD
is Qt in its own process, so it never shares a thread with Tk.

## State and logs (all under `%LOCALAPPDATA%\Umay` unless noted)

`chat_logs/` (next to the exe), `memory.log`, `companion.log`, `calls.log`, `credit_log.sqlite`,
`router_shadow.jsonl`, `spotify.log`, `news_watch.json`, `markets.json`, `disk\knowledge.json`,
`claude_tasks\`, `voice\speech.log`, `voice\wake.log`, `voice\hands_worker.log`. Settings come from `.env`
(`paths.load_env`; the old `HANNAH_` prefix still works).

Related: [Module map](module-map.md), [Tools and confirmations](adding-a-tool.md), [Pitfalls](pitfalls.md)
