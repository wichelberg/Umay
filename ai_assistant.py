import json
import os
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

import requests
from pynput import keyboard
from tavily import TavilyClient

import i18n
import paths
import browser_tools
import calendar_tools
import chat_box
import credit_log
import day_plan
import disk_watch
import calls
import claude_terminal
import eyes
import face
import heavy_model
import hud
import input_tools
import local_llm
import market_outlook
import markets_follow
import media_tools
import news_follow
import pc_tools
import price_alerts
import reminder_tools
import router
import screen_tools
import sleep_mode
import spotify_tools
import steam_tools
import system_tools
import task_plan
import voice_confirm
import web_control
import web_find
import whatsapp_tools

AI_NAME = "Umay"
USER_NAME = os.environ.get("UMAY_USER_NAME", "").strip() or "You"

CHAT_LOG_DIR = paths.app_dir() / "chat_logs"
CHAT_LOG_DIR.mkdir(exist_ok=True)

MAX_TOOL_ROUNDS = 40  # a task done with the mouse and keyboard takes a round per click
STEP_ROUNDS = 12      # one step of a plan (task_plan)
CONFIRM_TIMEOUT_SECONDS = 300


def _call_with_retry(fn, retries=2, delay=2.0):
    """Retries on transient connection/server errors before giving up.
    Raises immediately on 4xx errors (bad key, rate limit, etc.) since retrying won't help."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except requests.exceptions.ConnectionError as e:
            last_error = e
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code < 500:
                raise
            last_error = e
        if attempt < retries:
            time.sleep(delay)
    raise last_error


_tavily_client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))  # .env is loaded by paths


def _load_personality():
    """Umay's persona: personality.md, bundled next to the code (paths.resource_dir), and how she talks (STYLE)."""
    return (paths.resource_dir() / "personality.md").read_text(encoding="utf-8").strip() + "\n\n" + STYLE


# How she talks (the owner, 2026-11-04: shorter, discreet, Jarvis-like lines, "dear" instead of "sir"; she built
# paragraphs for everything). Not in personality.md: that file is also the owner's Telegram persona for Claude.
STYLE = (
    "How you talk: like Jarvis, a composed and discreet assistant, but warm. Short, plain, goal-focused "
    "lines: usually one sentence, two or three only when the content needs it; longer only when the user asks "
    "for an explanation or details. Lead with the result. No filler: don't restate the request, don't describe "
    "the screen or a tool's output unless asked, no \"Let me know if you need anything else\", no \"I hope\", "
    "no \"Great question\". Call the user \"dear\" the way Jarvis says \"sir\" (never \"sir\"): often, at most "
    "once in a reply. The tone (these show the tone only, never their content): \"Done, dear.\" \"On it.\" "
    "\"Found it, dear. It's open now.\" \"I couldn't find that folder. Another name, perhaps?\""
)


# The last two rules are for the small local model: it added details no tool had returned ("you were
# stuck on input validation" for "the user talked about a Python homework") and emoji (2026-11-02).
TOOL_HINTS = (
    "Always reply in English, whatever language the user writes in. For WhatsApp use whatsapp_chats, "
    "whatsapp_messages and send_whatsapp_file, which work through the WhatsApp Desktop app; never WhatsApp "
    "Web in the browser. After a tool runs, say only what its result says: never add details it didn't "
    "return. No emoji. Use the mouse and keyboard (click, scroll, type_text, press_keys) only when no other "
    "tool can do the task: look_at_screen first, then one step at a time, calling the next tool right away "
    "without describing it first; answer only when the task is done or you are stuck. To work on another "
    "monitor (or when asked to move the cursor there), call move_mouse first. To find a page inside a website "
    "(a course, a setting, a product) use web_find_in_site; for Opera GX itself the web_* tools come before "
    "the mouse and keyboard."
)

# The small local model, partway through a task on the screen, often answers "Let me click the field..."
# and stops there (measured 2026-11-02). Such an answer gets GO_ON, at most NUDGES times per request.
SCREEN_TOOLS = {"look_at_screen", "click", "scroll", "type_text", "press_keys", "move_mouse"}
ANNOUNCES_STEP = re.compile(r"\b(let me|let's|i'll|i will|i'm going to|now i|next,? i)\b", re.IGNORECASE)
GO_ON = "Go on with the task: call the tool for that step now."
NUDGES = 3

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"

# Umay's one mode: a model + her persona, served through an OpenAI-compatible endpoint: the local model
# (local_llm.py, Ollama) unless UMAY_LLM=openrouter. Chat history is stored in OpenAI chat format;
# chat["mode"] is always "umay".
if local_llm.on():
    _provider = {"provider": "Ollama", "url": local_llm.CHAT_URL, "key_env": None, "model": local_llm.model(),
                 "local": True}
else:
    _provider = {"provider": "OpenRouter", "url": OPENROUTER_URL, "key_env": OPENROUTER_KEY_ENV,
                 "model": os.environ.get("OPENROUTER_MODEL", "").strip() or "google/gemini-3.7-flash",
                 "local": False}
MODES = {"umay": {**_provider, "system": f"{_load_personality()}\n\n{TOOL_HINTS}"}}

_state = {"listener": None, "chat": None, "log_path": None}  # chat/log_path: the open text box
_lock = threading.Lock()
# The text box, yes/no box and the pet's lines (no window toggle any more): UMAY_LANGUAGE, English by default.
_language = os.environ.get("UMAY_LANGUAGE", "").strip().lower() or "en"
if _language not in i18n.STRINGS:
    _language = i18n.DEFAULT_LANGUAGE


# A query asking for something recent searches only the last month. The local model doesn't put the year
# in its queries (told to, it wrote "2024 2025"): "most recent Formula 1 race winner" got 2024's Monaco GP,
# with time_range "month" the October 2026 race (2026-11-02).
RECENT_QUERY = re.compile(r"\b(latest|recent|newest|current|news|today|tonight|yesterday|now|this (week|month))\b",
                          re.IGNORECASE)


def web_search(query: str) -> str:
    """Searches the web for current, up-to-date, or real-world information.

    Use this whenever the answer depends on recent, specific, or verifiable
    facts (news, prices, specs, dates, current events) rather than general
    knowledge you're already confident about.

    Args:
        query: The search query to look up on the web.
    """
    credit_log.before_search()
    try:
        response = _tavily_client.search(query, max_results=5,
                                         **({"time_range": "month"} if RECENT_QUERY.search(query) else {}))
    except Exception as e:
        return i18n.get(_language, "web_search_failed", error=e)

    results = response.get("results", [])
    if not results:
        return i18n.get(_language, "web_search_no_results")

    return "\n".join(
        f"- {r.get('title', '')} ({r.get('url', '')})\n  {r.get('content', '')}"
        for r in results
    )


def search_memory(query: str) -> str:
    """Searches past saved conversations for something the user refers to.

    Use this when the user asks whether you remember something from an
    earlier conversation, or references something discussed before.

    Args:
        query: Keywords describing what to look for in past conversations.
    """
    keywords = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
    if not keywords:
        return i18n.get(_language, "memory_no_keywords")

    current_log = _state.get("log_path")
    matches = []
    for log_file in sorted(CHAT_LOG_DIR.glob("*.txt")):
        if log_file == current_log:
            continue  # skip the still-open current session
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        seen_contexts = set()
        for i, line in enumerate(lines):
            if any(kw in line.lower() for kw in keywords):
                context = "\n".join(lines[max(0, i - 1): i + 2])
                if context in seen_contexts:
                    continue
                seen_contexts.add(context)
                matches.append(f"[{log_file.stem}]\n{context}")

    if not matches:
        return i18n.get(_language, "memory_no_matches")
    return "\n\n".join(matches[:10])


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Searches the web for current, up-to-date, or real-world information. "
                "Use this whenever the answer depends on recent, specific, or verifiable "
                "facts (news, prices, specs, dates, current events) rather than general "
                "knowledge you're already confident about."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query to look up on the web."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "Searches past saved conversations for something the user refers to. "
                "Use this when the user asks whether you remember something from an "
                "earlier conversation, or references something discussed before."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords describing what to look for in past conversations."},
                },
                "required": ["query"],
            },
        },
    },
] + (pc_tools.TOOLS + browser_tools.TOOLS + system_tools.TOOLS + steam_tools.TOOLS
     + screen_tools.TOOLS + input_tools.TOOLS + eyes.TOOLS + face.TOOLS + claude_terminal.TOOLS + calls.TOOLS + media_tools.TOOLS + spotify_tools.TOOLS + reminder_tools.TOOLS + calendar_tools.TOOLS + whatsapp_tools.TOOLS
     + web_control.TOOLS + web_find.TOOLS + sleep_mode.TOOLS + news_follow.TOOLS + markets_follow.TOOLS + market_outlook.TOOLS
     + price_alerts.TOOLS
     + day_plan.TOOLS)

TOOL_FUNCTIONS = {
    "web_search": web_search,
    "search_memory": search_memory,
    **pc_tools.TOOL_FUNCTIONS,
    **browser_tools.TOOL_FUNCTIONS,
    **system_tools.TOOL_FUNCTIONS,
    **steam_tools.TOOL_FUNCTIONS,
    **screen_tools.TOOL_FUNCTIONS,
    **input_tools.TOOL_FUNCTIONS,
    **eyes.TOOL_FUNCTIONS,
    **face.TOOL_FUNCTIONS,
    **claude_terminal.TOOL_FUNCTIONS,
    **calls.TOOL_FUNCTIONS,
    **media_tools.TOOL_FUNCTIONS,
    **spotify_tools.TOOL_FUNCTIONS,
    **reminder_tools.TOOL_FUNCTIONS,
    **calendar_tools.TOOL_FUNCTIONS,
    **whatsapp_tools.TOOL_FUNCTIONS,
    **web_control.TOOL_FUNCTIONS,
    **web_find.TOOL_FUNCTIONS,
    **sleep_mode.TOOL_FUNCTIONS,
    **news_follow.TOOL_FUNCTIONS,
    **markets_follow.TOOL_FUNCTIONS,
    **market_outlook.TOOL_FUNCTIONS,
    **price_alerts.TOOL_FUNCTIONS,
    **day_plan.TOOL_FUNCTIONS,
}


# While these run the HUD's orb shows "researching"; while any other tool runs, "working".
RESEARCH_TOOLS = {"web_search", "web_read_page", "search_youtube", "search_memory", "web_find_in_site",
                  "web_browser_data"}
# Their results come from outside (web pages, search results, other people's messages): after one of them,
# every confirm in that request carries a warning and every screen step asks (plan 20b, strict mode;
# pc_tools.mark_untrusted). web_control's tools also mark it themselves, with the links they saw.
UNTRUSTED_TOOLS = {"web_search", "web_read_page", "web_act", "web_tabs", "web_find_in_site", "web_browser_data",
                   "search_youtube", "whatsapp_messages", "whatsapp_chats"}


def _ask_confirmation(key, **kwargs):
    """Called from the worker thread by pc_tools before any change on the PC (a Telegram request asks on
    Telegram instead): she asks aloud and listens for yes or no (voice_confirm). Only when her voice
    can't (a game, no microphone) a yes/no box in the text box's neon look shows; blocks until it's
    answered (no after CONFIRM_TIMEOUT_SECONDS)."""
    question = i18n.render(_language, key, **kwargs)
    answer = voice_confirm.ask(question)
    if answer is not None:
        return answer
    return chat_box.confirm(i18n.get(_language, "confirm_title"), question,
                            i18n.get(_language, "confirm_yes"), i18n.get(_language, "confirm_no"),
                            CONFIRM_TIMEOUT_SECONDS)


pc_tools.confirm_handler = _ask_confirmation


def _notify(key, **kwargs):
    """Reports a finished background job started from the PC: in the text box if it's open,
    otherwise wherever pc_tools.fallback_notify sends it (Telegram)."""
    text = i18n.render(_language, key, **kwargs)
    if chat_box.is_open():
        chat_box.add(AI_NAME, text, "her")
    else:
        pc_tools.fallback_notify(text)


pc_tools.notify_handler = _notify


def answer_message(chat, text, language=None, source="other"):
    """Like _send_message, but turns any failure into a user-facing message instead of raising.
    `language` overrides the window's UI language for these messages.
    `source` (box, telegram, voice) is where the request came from, for the credit log."""
    lang = language or _language
    mode = MODES[chat["mode"]]
    if mode["key_env"] and not os.environ.get(mode["key_env"], "").strip():
        return i18n.get(lang, "invalid_api_key", provider=mode["provider"], env=mode["key_env"])
    try:
        with credit_log.activity(source, text):
            return _send_message(chat, text, source)
    except requests.exceptions.ConnectionError:
        return i18n.get(lang, "connection_error", provider=mode["provider"])
    except requests.exceptions.HTTPError as e:
        if e.response is None:
            return i18n.get(lang, "generic_error", error=e)
        status, body = e.response.status_code, e.response.text
    except Exception as e:
        return i18n.get(lang, "generic_error", error=e)

    if status in (401, 403):
        return i18n.get(lang, "invalid_api_key", provider=mode["provider"], env=mode["key_env"])
    if status == 404:
        return i18n.get(lang, "model_not_found", provider=mode["provider"], model=mode["model"])
    if status == 429:
        return i18n.get(lang, "rate_limited")
    if status >= 500:
        return i18n.get(lang, "server_overloaded", provider=mode["provider"])
    return i18n.get(lang, "generic_error", error=body)


def new_chat():
    """A chat session: its mode plus the history in OpenAI chat format (system
    prompt excluded; it's added per request)."""
    return {"mode": "umay", "messages": []}


# Last in the prompt, where the small local model heeds it: with the rule only in TOOL_HINTS it answered a
# Turkish message in (broken) Turkish (2026-11-02). After the clock, it costs ~20 uncached tokens a request.
# Its answers after a tool still came in Turkish (the prompt is ~8,000 tokens back by then), so the local
# model also gets LANGUAGE_REMINDER after the latest user message (in the request only, not the history).
LANGUAGE_RULE = "Reply in English only, even when the user writes in another language."
LANGUAGE_REMINDER = "\n\n(Reply in English.)"


def _system_prompt(mode):
    now = datetime.now()
    clock = f"Current local date and time: {now:%Y-%m-%d %H:%M} ({now:%A})."
    return f"{mode['system']}\n\n{clock}\n{LANGUAGE_RULE}" if mode["system"] else f"{clock}\n{LANGUAGE_RULE}"


def _tools(mode, tools=None):
    return TOOLS if tools is None else tools


def _headers(mode):
    headers = {"Content-Type": "application/json", "X-Title": "Umay"}
    if mode["key_env"]:
        headers["Authorization"] = f"Bearer {os.environ.get(mode['key_env'], '').strip()}"
    return headers


def _request_extras(mode):
    """OpenRouter reports each request's cost; the local model is told not to think first (Qwen3.5
    reasons before every answer by default, which is seconds of waiting in a spoken conversation)."""
    return {"reasoning_effort": "none"} if mode["local"] else {"usage": {"include": True}}


def _post(mode, body, timeout):
    """One request to the mode's endpoint (the local model counts as busy meanwhile, for voice_guard)."""
    if not mode["local"]:
        return requests.post(mode["url"], headers=_headers(mode), json=body, timeout=timeout)
    local_llm.ensure_model()
    with local_llm.working():
        # The first request after a game or a restart also loads the model (~5-10 s from disk).
        return requests.post(mode["url"], headers=_headers(mode), json=body, timeout=max(timeout, 120))


def _with_reminder(mode, messages):
    """messages for the request: for the local model, the latest user text gets LANGUAGE_REMINDER."""
    if not mode["local"]:
        return messages
    last = max((i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m.get("content"), str)),
               default=None)
    if last is None:
        return messages
    return messages[:last] + [{**messages[last], "content": messages[last]["content"] + LANGUAGE_REMINDER}] \
        + messages[last + 1:]


def _openai_compat_request(mode, messages, tools=None):
    """Returns (content, tool_calls, cost_in_usd) for the next assistant turn. `tools`: the tool schemas the
    model may use (all of them by default; one step of a plan gets fewer, an answer-only step none)."""
    schemas = _tools(mode, tools)
    response = _post(mode, {
        "model": mode["model"],
        "messages": [{"role": "system", "content": _system_prompt(mode)}] + _with_reminder(mode, messages),
        **({"tools": schemas} if schemas else {}),
        **_request_extras(mode),
    }, timeout=60)
    response.raise_for_status()
    data = response.json()
    credit_log.record(mode["model"], data.get("usage"))
    message = data["choices"][0]["message"]
    tool_calls = message.get("tool_calls") or []
    for tc in tool_calls:
        tc["id"] = tc.get("id") or f"call_{uuid.uuid4().hex[:12]}"  # some models leave ids empty
    return message.get("content") or "", tool_calls, float((data.get("usage") or {}).get("cost") or 0)


# Ollama: "request (16445 tokens) exceeds the available context size (16384 tokens)"; OpenRouter's providers:
# "maximum context length is ...". The history had no limit: on Telegram (kept for an hour between messages) a
# few screen tasks filled the local model's 16k window, and every later message failed, each a little longer
# than the last, since the failed message stayed in it (2026-11-03).
TOO_LONG = re.compile(r"exceeds the available context|context length|context size|too many tokens", re.IGNORECASE)


def _too_long(error):
    r = error.response
    return r is not None and r.status_code == 400 and bool(TOO_LONG.search(r.text or ""))


SUMMARY_PREFIX = "[Summary of our conversation so far]\n"
SUMMARY_PROMPT = ("Summarize this conversation between the user and Umay, their assistant, as briefly as you can, "
                  "in at most 6 short bullet points in English: what the user asked for, what Umay actually did, "
                  "facts and decisions that still matter, anything left open. Only what the conversation says: "
                  "if something wasn't done, don't say it was. Only the bullet points.\n\n")
SUMMARY_SOURCE_CHARS = 24000  # ~7,000 tokens of the conversation, its newest part; the request has no tools
SUMMARY_TOOL_CHARS = 300


def _turn_starts(messages):
    """Where the user's turns start: their own messages (not a screenshot, not GO_ON). A cut there leaves no
    tool result without its call."""
    return [i for i, m in enumerate(messages)
            if m["role"] == "user" and isinstance(m.get("content"), str) and m["content"] != GO_ON]


def _drop_oldest_turn(messages):
    """Drops (in place) everything before the second turn. False when only the current turn is left."""
    cut = next((i for i in _turn_starts(messages) if i > 0), None)
    if cut is None:
        return False
    del messages[:cut]
    return True


def _transcript(messages):
    lines = []
    for m in messages:
        content = m.get("content")
        if not isinstance(content, str) or content == GO_ON:
            continue  # screenshots
        if m["role"] == "tool":
            lines.append(f"(tool result: {content[:SUMMARY_TOOL_CHARS]})")
        elif m["role"] == "user":
            lines.append(content if content.startswith(SUMMARY_PREFIX) else f"User: {content}")
        elif content or m.get("tool_calls"):
            called = ", ".join(tc["function"]["name"] for tc in m.get("tool_calls") or [])
            lines.append(f"Umay: {content}" + (f" (called {called})" if called else ""))
    return "\n".join(lines)[-SUMMARY_SOURCE_CHARS:]


def _summarize(mode, messages):
    response = _post(mode, {"model": mode["model"],
                            "messages": [{"role": "user", "content": SUMMARY_PROMPT + _transcript(messages)}],
                            **_request_extras(mode)}, timeout=90)
    response.raise_for_status()
    data = response.json()
    credit_log.record(mode["model"], data.get("usage"))
    return (data["choices"][0]["message"].get("content") or "").strip()


def ask_plain(prompt, timeout=90):
    """One question to Umay's model, no tools and no history (web_find picks its next step with it)."""
    mode = MODES["umay"]
    response = _post(mode, {"model": mode["model"], "messages": [{"role": "user", "content": prompt}],
                            **_request_extras(mode)}, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    credit_log.record(mode["model"], data.get("usage"))
    return (data["choices"][0]["message"].get("content") or "").strip()


web_find.ask_model = ask_plain


def _compact(mode, messages):
    """Replaces (in place) everything before the current turn with a short summary of it, an earlier summary
    included. False when there is nothing left to summarize or the summary fails."""
    starts = _turn_starts(messages)
    cut = starts[-1] if starts else 0
    old = messages[:cut]
    if not old or (len(old) == 1 and str(old[0].get("content")).startswith(SUMMARY_PREFIX)):
        return False
    try:
        summary = _summarize(mode, old)
    except Exception:
        return False
    if not summary:
        return False
    messages[:cut] = [{"role": "user", "content": SUMMARY_PREFIX + summary}]
    return True


def _request_fitting(mode, messages, tools=None):
    """The next assistant turn. When the history doesn't fit the model's context, what came before the current
    turn becomes a short summary; if that still doesn't fit (or can't be made), the oldest turns go."""
    while True:
        try:
            return _call_with_retry(lambda: _openai_compat_request(mode, messages, tools))
        except requests.exceptions.HTTPError as e:
            if not _too_long(e) or not (_compact(mode, messages) or _drop_oldest_turn(messages)):
                raise


def _drop_images(messages):
    """Replaces screenshots already answered from with a placeholder, so they aren't
    re-sent (and paid for) with every later message."""
    for m in messages:
        if isinstance(m.get("content"), list):
            m["content"] = "[screenshot from look_at_screen, no longer attached]"


def _send_message(chat, user_text, source="other"):
    """Sends a message, resolving any tool calls, and returns the final answer text.
    chat["messages"] is mutated in place so the conversation history keeps growing.
    A tool may return {"text": ..., "image": data_uri} or {"text": ..., "images": [data_uri, ...]};
    the images are shown to the model in a message right after the tool results."""
    messages = chat["messages"]
    messages.append({"role": "user", "content": user_text})
    pc_tools.new_request()  # strict mode (plan 20b) starts over: nothing untrusted read yet
    look = eyes.command(user_text, max_words=6)
    if look:  # "eyes on / off": no model needed, and the small one might not call it right
        answer = eyes.switch(look)
        messages.append({"role": "assistant", "content": answer})
        return answer
    if calls.asked(user_text):  # "call me", "beni ara": the same
        answer = calls.call_owner("You asked me to call. I'm here.")
        messages.append({"role": "assistant", "content": answer})
        return answer
    task = claude_terminal.asked(user_text)
    if task is not None:  # "open Claude Code and ...": the same
        answer = claude_terminal.open_session(task)
        messages.append({"role": "assistant", "content": answer})
        return answer
    monitor = input_tools.asked(user_text)
    if monitor is not None:  # "move the mouse to the other monitor": the same
        input_tools.new_turn()
        _, answer = input_tools.move_to_monitor(monitor)
        answer = answer.rstrip(".") + ", dear."
        messages.append({"role": "assistant", "content": answer})
        return answer
    alarm = price_alerts.asked(user_text)
    answer = price_alerts.shortcut(alarm) if alarm else None
    if answer is not None:  # "BTC 80 bini geçerse haber ver": the 4b model mixed up "80 bin" and the direction
        credit_log.note_tool("price_alert")
        messages.append({"role": "assistant", "content": answer})
        return answer
    # "add Apple to the markets", then "follow Nvidia in the news" (whose "unfollow X" needs no "news"): the same
    market, follow = markets_follow.asked(user_text), None
    if market is None:
        follow = news_follow.asked(user_text)
    if market is not None or follow is not None:
        answer = markets_follow.run(*market) if market is not None else news_follow.run(*follow)
        messages.append({"role": "assistant", "content": answer})
        return answer
    music = spotify_tools.asked(user_text)
    if music is not None:  # "Spotify'da Tarkan çal", "turn Spotify down to 40": the 4b model got these wrong
        credit_log.note_tool("spotify")
        answer = spotify_tools.spoken(spotify_tools.spotify(**music))
        messages.append({"role": "assistant", "content": answer})
        return answer
    # Shadow only (router.py): what layer 1 would have done is logged next to what the model does; nothing runs.
    route = router.route(user_text)
    called, started, answer = [], time.monotonic(), ""
    input_tools.new_turn()
    heavy_model.new_request()  # its call budget (plan 21) starts over
    run = {"cost": 0.0}
    before = hud.current()  # the box, a spoken turn or nothing (Telegram): back to it at the end
    try:
        planned = _planned(chat, user_text, source, called, run)
        if planned is not None:  # a multi-step request, done as a plan (task_plan)
            answer = planned
            messages.append({"role": "assistant", "content": answer})
            return answer
        content = _tool_loop(MODES[chat["mode"]], messages, MAX_TOOL_ROUNDS, called, run)
        if content is None:
            return i18n.get(_language, "too_many_tool_calls")
        answer = content
        return content
    finally:
        if hud.current() in ("research", "work", "think") and before not in ("research", "work"):
            hud.activity(before)
        _drop_images(messages)
        if run["cost"]:
            _message_costs.append(run["cost"])
        router.log(route, source, called, time.monotonic() - started, answer)


def _tool_loop(mode, messages, rounds, called, run, tools=None):
    """Model turns and their tool calls until the model answers without one; returns that answer, or None when
    `rounds` ran out. `tools`: the tool schemas it may use (all by default); a call to any other is refused.
    Appends to `messages` and `called` in place and adds the cost to run["cost"]."""
    allowed = None if tools is None else {t["function"]["name"] for t in tools}
    on_screen, nudges = False, 0
    for _ in range(rounds):
        content, tool_calls, round_cost = _request_fitting(mode, messages, tools)
        run["cost"] += round_cost

        if not tool_calls:
            messages.append({"role": "assistant", "content": content})
            if on_screen and nudges < NUDGES and ANNOUNCES_STEP.search(content[-200:]):
                nudges += 1
                messages.append({"role": "user", "content": GO_ON})
                continue
            return content

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        images = []
        names = {tc["function"]["name"] for tc in tool_calls}
        on_screen = on_screen or bool(names & SCREEN_TOOLS)
        hud.activity("research" if names & RESEARCH_TOOLS else "work")
        for tc in tool_calls:
            fn_info = tc["function"]
            credit_log.note_tool(fn_info["name"])
            func = TOOL_FUNCTIONS.get(fn_info["name"])
            try:
                args = json.loads(fn_info.get("arguments") or "{}")
                called.append((fn_info["name"], args))
                if allowed is not None and fn_info["name"] not in allowed:
                    result = (f"{fn_info['name']} isn't one of this step's tools; use these: "
                              f"{', '.join(sorted(allowed))}.")
                else:
                    result = func(**args) if func else i18n.get(_language, "unknown_tool", name=fn_info["name"])
            except Exception as e:
                result = i18n.get(_language, "tool_error", error=e)
            if fn_info["name"] in UNTRUSTED_TOOLS:
                pc_tools.mark_untrusted()
            if isinstance(result, dict) and ("image" in result or "images" in result):
                images += result.get("images") or [result["image"]]
                result = result["text"]
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})
        hud.activity("think")
        if images:
            _drop_images(messages)  # only the newest screenshot: a task with many clicks fills the context
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": "[Screenshot taken by look_at_screen]"}]
                + [{"type": "image_url", "image_url": {"url": url}} for url in images],
            })
    return None


# --- Plans for multi-step requests (plan 21, task_plan) -----------------------------------------

RECENT_CHARS = 1500


def _recent_text(chat):
    """The conversation just before the current message, in short, for the planner (a follow-up like "now send
    it to Ali" needs it)."""
    lines = []
    for m in chat["messages"][:-1][-6:]:
        content = m.get("content")
        if isinstance(content, str) and content and content != GO_ON and m["role"] in ("user", "assistant"):
            lines.append(f"{'Owner' if m['role'] == 'user' else 'Umay'}: {content}")
    return "\n".join(lines)[-RECENT_CHARS:]


def _show(source, text):
    """A line for the owner while the request still runs: in the text box (box) or on Telegram; a spoken
    request just goes on (its answer is spoken at the end)."""
    if source == "box" and chat_box.is_open():
        chat_box.add(AI_NAME, text, "her")
    elif source == "telegram":
        pc_tools.current_notifier()("plan_note", text=text)


def _what_was_done(messages):
    """The tools a step called and the start of what they answered, for the heavy model's fix."""
    lines = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            lines += [f"called {tc['function']['name']}({tc['function'].get('arguments') or ''})"[:300]
                      for tc in m["tool_calls"]]
        elif m["role"] == "tool":
            lines.append(f"  -> {str(m.get('content'))[:300]}")
    return "\n".join(lines[-16:])


def _planned(chat, user_text, source, called, run):
    """A multi-step request becomes a plan the heavy model writes and the local model does step by step (plan
    21; the owner's choice 2026-11-05: show the plan and start at once). Returns the answer, or None when
    the request isn't multi-step or there's no plan (no heavy model, offline): then the usual tool loop
    answers. When the planner has questions, they are the answer, and the next message is taken as their
    answer (chat["pending_plan"])."""
    pending = chat.pop("pending_plan", None)
    if not heavy_model.on():
        return None
    if pending:
        request = f"{pending}\n(The owner's answer to my questions: {user_text})"
    elif task_plan.needs_plan(user_text, ask_plain):
        request = user_text
    else:
        return None
    hud.activity("think")
    plan = task_plan.make(request, _recent_text(chat), TOOLS, f"{datetime.now():%Y-%m-%d %A %H:%M}")
    if plan is None:
        return None
    if plan["ask_user"]:
        chat["pending_plan"] = request
        return i18n.get(_language, "plan_questions", questions="\n".join(f"- {q}" for q in plan["ask_user"]))
    _show(source, i18n.get(_language, "plan_shown", count=len(plan["steps"]),
                           steps=task_plan.plan_text(plan["steps"])))
    return _run_plan(request, plan["steps"], called, run)


def _run_plan(request, steps, called, run):
    """Each step in a fresh conversation with only its tools (task_plan.step_tools). A step that fails gets one
    new attempt written by the heavy model; if that fails too, or it gives up, the plan stops there."""
    mode = MODES["umay"]
    names = [t["function"]["name"] for t in TOOLS]
    results, retried, answer = [], set(), ""
    i = 0
    while i < len(steps):
        allowed = task_plan.step_tools(steps[i], names, last=i == len(steps) - 1)
        tools = [t for t in TOOLS if t["function"]["name"] in allowed]
        messages = [{"role": "user", "content": task_plan.step_prompt(request, steps, i, results)}]
        before = len(called)
        answer = _tool_loop(mode, messages, STEP_ROUNDS, called, run, tools)
        if not task_plan.failed(answer) and task_plan.skipped(steps[i], called[before:]):
            messages.append({"role": "user", "content": task_plan.not_done(steps[i])})
            answer = _tool_loop(mode, messages, STEP_ROUNDS, called, run, tools)
            if task_plan.skipped(steps[i], called[before:]):
                answer = ""  # still nothing done: a failed step
        if task_plan.failed(answer):
            new, why = (None, None) if i in retried else task_plan.fix(
                request, steps, i, results, answer or _what_was_done(messages), TOOLS)
            if new is None:
                return i18n.get(_language, "plan_stopped", step=i + 1, count=len(steps),
                                why=why or answer or i18n.get(_language, "plan_no_answer"),
                                done=task_plan.results_text(results))
            retried.add(i)
            steps = steps[:i] + [new] + steps[i + 1:]
            continue
        results.append(task_plan.short(answer))
        i += 1
    return answer


# --- OpenRouter credits ---------------------------------------------------------------

_message_costs = deque(maxlen=50)  # cost of each recent user message, all tool rounds included


def openrouter_balance(timeout=10):
    """Remaining OpenRouter credit in USD, or None if it can't be read."""
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {os.environ.get(OPENROUTER_KEY_ENV, '').strip()}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return float(data["total_credits"]) - float(data["total_usage"])
    except Exception:
        return None


def credits_text(lang):
    remaining = openrouter_balance()
    if remaining is None:
        return i18n.get(lang, "openrouter_credits_failed")
    text = i18n.get(lang, "openrouter_credits", remaining=remaining)
    if _message_costs:
        average = sum(_message_costs) / len(_message_costs)
        if average > 0:
            text += "\n" + i18n.get(lang, "openrouter_estimate", messages=int(remaining / average),
                                    average=average, count=len(_message_costs))
    return text


def get_openrouter_credits() -> str:
    return credits_text("en")


if not MODES["umay"]["local"]:  # the local model's replies cost nothing
    TOOLS.append({
        "type": "function",
        "function": {
            "name": "get_openrouter_credits",
            "description": "Shows the user's remaining OpenRouter credit (what Umay's replies cost) and roughly "
                           "how many more messages it covers at the recent average cost.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    })
    TOOL_FUNCTIONS["get_openrouter_credits"] = get_openrouter_credits


def _get_tavily_credits():
    """Returns (kind, data) where kind is 'ok' | 'unknown' | 'error', for re-rendering on language toggle."""
    try:
        resp = requests.get(
            "https://api.tavily.com/usage",
            headers={"Authorization": f"Bearer {os.environ.get('TAVILY_API_KEY')}"},
            timeout=5,
        )
        resp.raise_for_status()
        account = resp.json().get("account", {})
        usage, limit = account.get("plan_usage"), account.get("plan_limit")
        if usage is None or limit is None:
            return ("unknown", None)
        return ("ok", {"remaining": limit - usage, "limit": limit})
    except Exception:
        return ("error", None)


def _tavily_remaining():
    kind, data = _get_tavily_credits()
    return data["remaining"] if kind == "ok" else None


# Before / after balances for the credit log; "before" holds the request up, so it gets a short timeout.
# The local model costs nothing: no balance to read around its replies.
credit_log.configure(balance=None if MODES["umay"]["local"] else lambda: openrouter_balance(timeout=4),
                     tavily=_tavily_remaining)


def _new_log_path():
    return CHAT_LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"


def _log_line(who, text):
    path = _state.get("log_path")
    if path is None:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{who}: {text}\n")


def _box_open():
    with _lock:
        _state["chat"] = new_chat()
        _state["log_path"] = _new_log_path()
    hud.activity("listen")


def _box_close():
    with _lock:
        chat = _state["chat"]
        _state["chat"] = None
        _state["log_path"] = None
    import voice_session

    if not voice_session.active():  # a spoken conversation keeps her busy
        hud.activity(None)


def _box_send(text):
    """Enter in the text box: Umay thinks (the orb too), then her answer shows in the box while the
    orb talks for about as long as it takes to read. Silent: the owner chose text for the box."""
    chat = _state["chat"]
    if chat is None:
        return
    chat_box.add(USER_NAME, text, "you")
    _log_line(USER_NAME, text)
    chat_box.thinking(True)
    hud.activity("think")

    hint = chat.pop("hint", "")  # reach_out(hint=...): for this answer only

    def work():
        answer = answer_message(chat, text + hint, source="box")
        _log_line(AI_NAME, answer)
        chat_box.thinking(False)
        chat_box.add(AI_NAME, answer, "her")
        hud.activity("talk")
        time.sleep(min(10.0, max(2.0, len(answer) / 18)))
        if chat_box.is_open() and _state["chat"] is chat:
            hud.activity("listen")

    threading.Thread(target=work, daemon=True).start()


def toggle_chat_box():
    """Thread-safe: opens the text box beside the HUD's orb (bottom right without the HUD), or closes it:
    Ctrl+F1, or a click on the orb."""
    chat_box.toggle(_box_open, _box_send, _box_close, i18n.get(_language, "box_hint"),
                    i18n.get(_language, "box_thinking"))


def reach_out(text, hint=""):
    """Umay starts a written conversation herself (companion.py: the room is loud, a meeting): the text box
    opens beside the orb without taking the keyboard, her line in it, and the owner answers there. `hint` goes
    to the model with that answer only."""
    if not chat_box.is_open():
        chat_box.toggle(_box_open, _box_send, _box_close, i18n.get(_language, "box_hint"),
                        i18n.get(_language, "box_thinking"), only_open=True)
        for _ in range(60):  # _box_open runs on the box's thread
            if _state["chat"] is not None:
                break
            time.sleep(0.05)
    chat = _state["chat"]
    if chat is None:
        pc_tools.fallback_notify(text)
        return
    chat["messages"].append({"role": "assistant", "content": text})
    if hint:
        chat["hint"] = hint
    _log_line(AI_NAME, text)
    chat_box.add(AI_NAME, text, "her")


def persona():
    """Her persona (personality.md), for what she says on her own (companion.py)."""
    return _load_personality()


def toggle_hud():
    """Ctrl+F2: hides the HUD, or shows it again (starting it if needed); off the hotkey's thread."""
    threading.Thread(target=hud.toggle, daemon=True).start()


def open_disk_panel():
    """Thread-safe: the storage panel's detail view, the disk scan (a click on the HUD's "Disk: new findings"
    line)."""
    hud.open_detail("storage")


# --- what the HUD's detail views ask of Umay's process (hud.on) ------------------------------------------

def _hud_balances(_event):
    """The credits panel's OpenRouter and Tavily credit left."""
    hud.tell({"balances": {"openrouter": openrouter_balance(timeout=6), "tavily": list(_get_tavily_credits())}})


def _hud_disk_state(_event=None):
    hud.tell({"disk": {"running": disk_watch.running(), "progress": disk_watch.progress()}})


def _hud_disk_scan(_event):
    disk_watch.scan_now()
    _hud_disk_state()


def _hud_disk_delete(event):
    """Deletes a scanned item the owner confirmed in the storage detail view (it asked, listing what goes
    with it and what breaks), the way its kind is deleted (disk_actions.plan)."""
    import disk_actions
    import disk_tools
    import panel_text

    scan = disk_watch.latest()
    item = scan.by_id().get(event.get("id")) if scan is not None else None
    p = disk_actions.plan(item) if item is not None else None
    if p is None:
        hud.tell({"disk_result": {"id": event.get("id"), "ok": False,
                                  "text": i18n.get(_language, "disk_failed", error="item not found")}})
        return
    result = disk_actions.execute(p, disk_tools.Places.real())
    if result.ok and not result.started:
        disk_watch.after_delete(scan, item)
    text, ok = panel_text.result_text(_language, item, result)
    hud.tell({"disk_result": {"id": item.id, "ok": ok, "text": text}})


def wire_hud():
    """What the HUD's detail views can ask for, and the disk scan's progress pushed to them."""
    hud.on("balances", _hud_balances)
    hud.on("disk_state", _hud_disk_state)
    hud.on("disk_scan", _hud_disk_scan)
    hud.on("disk_delete", _hud_disk_delete)
    disk_watch.listen(_hud_disk_state)


def ask_flash(prompt, what="", source="disk"):
    """One question to Umay's model with no tools and no history; returns
    the answer's text. The disk scanner uses it for folders no rule knows (disk_memory.describe)."""
    mode = MODES["umay"]
    if mode["key_env"] and not os.environ.get(mode["key_env"], "").strip():
        raise RuntimeError(f"{mode['key_env']} is not set")

    def request():
        response = _post(mode, {"model": mode["model"], "messages": [{"role": "user", "content": prompt}],
                                **_request_extras(mode)}, timeout=90)
        response.raise_for_status()
        return response.json()

    with credit_log.activity(source, what):
        data = _call_with_retry(request)
        credit_log.record(mode["model"], data.get("usage"))
    return data["choices"][0]["message"].get("content") or ""


HOTKEY = "<ctrl>+<f1>"       # the text box
HUD_HOTKEY = "<ctrl>+<f2>"   # hide / show the HUD


def current_language():
    return _language


def start_ai_assistant():
    """Starts the global hotkeys: Ctrl+F1 the text box, Ctrl+F2 hides / shows the HUD."""
    if _state["listener"] is not None:
        return  # already running
    listener = keyboard.GlobalHotKeys({HOTKEY: toggle_chat_box, HUD_HOTKEY: toggle_hud})
    listener.daemon = True
    listener.start()
    _state["listener"] = listener


def stop_ai_assistant():
    listener = _state["listener"]
    if listener is not None:
        listener.stop()
        _state["listener"] = None
