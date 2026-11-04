---
title: Module map
date: 2026-11-05
tags: [umay, modules]
---

# Module map

Line counts as of 2026-11-05. Files over ~800 lines: read the part you need (grep for the `def`), not the
whole file. Each module starts with a docstring that says what it does and why. Read that first. Tests:
`tests/test_<module>.py`.

## Core

| File | Lines | Owns |
|---|---|---|
| `main.py` | 217 | Startup, single instance, alarm supervisor |
| `ai_assistant.py` | 888 | Provider/model, prompt, `TOOLS` registry, shortcuts, tool loop, compaction, credits, text box glue, HUD events |
| `router.py` | 1079 | Local layer-1 router (shadow only), `python router.py review` |
| `local_llm.py` | 112 | Ollama model, its 16k copy, load/unload, VRAM |
| `paths.py` | 93 | App/resource/voice folders, `.env` loading, PyInstaller env cleanup |
| `i18n.py` / `i18n.example.py` | 912 | Every UI string, `en` + `tr` (`i18n.get`, `i18n.render`). `i18n.py` is gitignored: change both |
| `credit_log.py` | 263 | Cost of each paid request (sqlite) |
| `conversation_memory.py` | 254 | Judging, deleting and summarizing old `chat_logs` |
| `tkpost.py` | 40 | Cross-thread Tk calls (`Mailbox`) |

## Inputs and channels

| File | Lines | Owns |
|---|---|---|
| `chat_box.py`, `layered.py` | 354, 89 | Text box and yes/no box; Win32 layered windows |
| `telegram_listener.py` | 378 | Telegram through claude_comm's router, `/` commands |
| `voice_session.py`, `wake.py` | 275, 368 | Spoken conversation; "Hey Umay" listener |
| `voice_confirm.py` | 106 | Yes/no asked aloud |
| `voice.py` | 917 | STT/TTS/RVC worker management, sentence pipeline |
| `voice_guard.py` | 300 | Keeps voice models ready, unloads during games/VRAM pressure |
| `listen_volume.py`, `glow.py` | 231, 334 | Lowering volume while listening; screen-edge light |
| `calls.py`, `call_audio.py`, `call_devices.py` | 525, 149, 92 | WhatsApp calls through WhatsApp Beta + VB-CABLE |
| `companion.py`, `day_plan.py` | 804, 287 | Umay starting talk herself; the day's plan and tally |

## Tools the model calls (each exports `TOOLS` + `TOOL_FUNCTIONS`)

`pc_tools.py` (539, files/apps, **confirm channels**), `system_tools.py` (723, close apps, Python runs,
shutdown, status), `browser_tools.py` (220), `web_control.py` (615, Opera extension), `screen_tools.py`
(247), `input_tools.py` (445, mouse/keyboard), `media_tools.py` (89), `spotify_tools.py` (600, local) +
`spotify_web.py` (575, Web API), `steam_tools.py` (209), `whatsapp_tools.py` (1031, UI Automation),
`reminder_tools.py` (224), `calendar_tools.py` (248, .ics + plan items), `claude_terminal.py` (204),
`sleep_mode.py` (669), `news_follow.py` (134), `markets_follow.py` (226), `market_outlook.py` (175),
`eyes.py` (213), `face.py` (150), `calls.py`, `day_plan.py`.

## Alarms and health

`config_loader.py`, `check_event.py`, `alert.py`, `alarm_ring.py`, `reminder_tools.py` (events in
`config.json`); `health_monitor.py` (341, GPU temp/RAM/CPU/disk escalation); `holiday_days.py`.

## HUD (Qt process)

`hud.py` (203, Umay's side), `hud_app.py` (1168, the Qt app), `hud_detail.py` (overlay), `hud_views.py`
(weather/vitals/calendar), `hud_disk.py`, `hud_credits.py`, `hud_news.py`, `hud_markets.py`, `hud_paint.py`
(colors/drawing), `hud_layout.py` (pure, monitors), `hud_windows.py` (where the orb goes), `hud_data.py`,
`hud_feeds.py` (pure data, no Qt), `panel_text.py` (pure, shared text).

## Disk

`disk_tools.py` (1300, the scanner), `disk_actions.py` (deleting by kind, `_MEI` cleanup), `disk_memory.py`,
`disk_watch.py` (daily scan). `DiskManagement/` holds two older standalone scripts, not imported.

## Eyes and voice training

`hand_gesture.py` (pure, testable), `hands_worker.py`, `face_worker.py`; `speech_worker.py`,
`setup_voice_env.py`, `voice_data.py`, `voice_recorder.py`, `train_stt.py`, `stt_eval.py`, `tts_text.py`,
`tts_worker.py`, `piper_worker.py`, `voice_worker.py`.

## Other folders

`tests/` (unittest, `disk_fixture.py`), `assets/`, `sounds/`, `development/` (plan), `build/` and `dist/`
(PyInstaller output), `UI/` (a reference video only), `chat_logs/` (gitignored).

Related: [Architecture](architecture.md), [Tools and confirmations](adding-a-tool.md)
