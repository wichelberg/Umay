"""Plans for multi-step requests (plan 21a/b): the heavy model writes the steps, the local 4b does them.

Why: the 4b, given all ~67 tools and a long request, loses its way (it planned the owner's "find jobs from my
CV" without ever reading the CV, 2026-11-05). Claude Code Haiku wrote sound 6-8 step plans over Umay's real
tools for the owner's three example tasks, with no invented tools once its answer was held to a JSON schema
(development/planned.txt, item 21).

- needs_plan: the 4b itself says PLAN or SIMPLE (no tools, ~1 s; 16/16 right on the owner's examples and
  simple requests, 2026-11-05). Requests under MIN_WORDS words are simple without asking.
- make: the heavy model's plan, checked: only real tool names, at most MAX_STEPS steps, at most 2 questions.
- step_tools: a step sees only its tools and their group mates (21b): ~10 tools instead of ~67, so the 4b
  picks the right one and its 16k context isn't filled by the tool list.
- step_prompt: what the 4b sees for one step: the request, the plan, what the earlier steps found, this step.
- fix: a step that failed gets one new attempt, rewritten by the heavy model with what went wrong.
ai_assistant._run_plan runs it all.
"""
import json
import re

import heavy_model

MIN_WORDS = 6
MAX_STEPS = 10
MAX_QUESTIONS = 2
RESULT_CHARS = 600

CLASSIFY_PROMPT = (
    "You decide whether a request to a PC assistant needs a step-by-step plan. Answer PLAN if doing it takes "
    "several different actions in a row (for example open a site, find a page, download a file; or read a file, "
    "then search the web, then write a summary). Answer SIMPLE if one action or one tool call does it (open an "
    "app, play a song, a question, set an alarm, check the weather, search one thing). Answer with one word: "
    "PLAN or SIMPLE.\n\nRequest: ")

# Group mates come along with a step's tools (21b), so a step that has to fall back (web_act -> click) can.
GROUPS = [
    {"list_directory", "search_files", "read_file", "create_folder", "write_file", "move_path", "delete_path",
     "organize_downloads", "open_path"},
    {"web_search", "search_memory", "open_in_browser", "search_youtube", "open_youtube_result", "web_tabs",
     "web_read_page", "web_act", "web_browser_data", "control_video", "web_find_in_site"},
    {"look_at_screen", "send_screenshot", "click", "scroll", "type_text", "press_keys", "move_mouse"},
    {"media_key", "set_volume", "spotify", "control_video"},
    {"whatsapp_chats", "whatsapp_messages", "send_whatsapp_file", "call_owner"},
    {"find_applications", "launch_application", "list_open_apps", "close_app", "list_processes", "end_process",
     "open_in_vscode", "open_terminal", "run_python", "list_runs", "stop_run"},
    {"list_alarms", "add_reminder", "set_alarm_active", "delete_alarm", "add_to_calendar", "plan_day",
     "read_plan_item"},
]

PLANNER = """You are the planner for Umay, a desktop assistant on the owner's Windows PC.
A small local model (qwen3.5 4b) carries out your plan one step at a time. At each step it sees only the
request, your plan, short results of the earlier steps, and the tools you list for that step (plus related
ones), so every step must be self-contained and concrete. It can see the screen and click (look_at_screen,
click, type_text, ...), but prefer a dedicated tool whenever one exists (web_* tools for Opera GX).

Rules:
- Use only the tools listed below, by their exact names. Never invent a tool.
- 2 to 10 steps. Each step: what to do, which tools (1-4), how to check it worked, and whether it is
  irreversible (sends, deletes, buys, submits or can't be undone).
- The last step answers the owner (Umay always answers in English): what was done, and the result they
  asked for.
- ask_user: only questions without which the task can't be done at all (at most 2). Leave it empty when a
  sensible default works; say the default in the step instead. Don't ask about a login in advance (the
  browser is usually signed in already): the step that opens the site checks the page, and if it shows a
  sign-in, it stops there and tells the owner to sign in themselves. Never ask for or type passwords.
- The owner's folders: C:\\Users\\merty\\Desktop, \\Documents, \\Downloads. Browser: Opera GX with Umay's
  extension (the web_* tools work in it). Today's date is given with the request.

Umay's tools (name(parameters): what it does):
"""

SCHEMA = {
    "type": "object", "required": ["steps", "ask_user"],
    "properties": {
        "steps": {"type": "array", "items": {
            "type": "object", "required": ["do", "tools", "check", "irreversible"],
            "properties": {"do": {"type": "string"}, "tools": {"type": "array", "items": {"type": "string"}},
                           "check": {"type": "string"}, "irreversible": {"type": "boolean"}}}},
        "ask_user": {"type": "array", "items": {"type": "string"}}}}

FIX_SCHEMA = {
    "type": "object", "required": ["give_up", "do", "tools", "why"],
    "properties": {"give_up": {"type": "boolean"}, "do": {"type": "string"},
                   "tools": {"type": "array", "items": {"type": "string"}}, "why": {"type": "string"}}}

FIX_PROMPT = """A step of the plan below failed. Rewrite that step so the small model can do it another way
(other tools, smaller moves, a different place to look), or give up if it can't be done with these tools
(then say why in one sentence for the owner).

Request: {request}
Plan:
{plan}
Results so far:
{results}
The step that failed: {step}. {failed}
What happened: {what}"""

# Looked for in the answer's first clause only: "Sorry, I still couldn't open it." failed, "Found 3 listings;
# I couldn't find more." didn't.
FAILED = re.compile(r"\b(couldn['’]?t|could not|can['’]?t|cannot|unable|wasn['’]?t able|failed)\b", re.IGNORECASE)


def needs_plan(text, ask_local):
    """True when the request takes several actions in a row. ask_local(prompt) -> the 4b's answer."""
    if len(text.split()) < MIN_WORDS:
        return False
    try:
        return ask_local(CLASSIFY_PROMPT + text).strip().upper().startswith("PLAN")
    except Exception:  # the local model is down: no plan, the normal tool loop answers
        return False


def _first_sentence(text, limit=220):
    text = " ".join(str(text).split())
    cut = text.find(". ")
    return (text[:cut + 1] if 0 < cut < limit else text[:limit]).strip()


def catalog(tools):
    """One line per tool: name(params, with the choices of an enum param): the first sentence of its description."""
    lines = []
    for tool in tools:
        fn = tool["function"]
        params = []
        for name, spec in (fn.get("parameters") or {}).get("properties", {}).items():
            choices = spec.get("enum") or (spec.get("items") or {}).get("enum")
            params.append(f"{name}: {'|'.join(map(str, choices))}" if choices else name)
        lines.append(f"- {fn['name']}({', '.join(params)}): {_first_sentence(fn.get('description', ''))}")
    return "\n".join(lines)


def check(plan, names):
    """The plan with only real tools, at most MAX_STEPS steps and MAX_QUESTIONS questions; None if unusable."""
    if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
        return None
    steps = []
    for step in plan["steps"][:MAX_STEPS]:
        if not isinstance(step, dict) or not str(step.get("do", "")).strip():
            continue
        tools = [t for t in step.get("tools") or [] if isinstance(t, str) and t in names]
        steps.append({"do": str(step["do"]).strip(), "tools": tools, "check": str(step.get("check", "")).strip(),
                      "irreversible": bool(step.get("irreversible"))})
    if not steps:
        return None
    questions = [str(q).strip() for q in plan.get("ask_user") or [] if str(q).strip()][:MAX_QUESTIONS]
    return {"steps": steps, "ask_user": questions}


def make(request, recent, tools, today):
    """The heavy model's plan for `request` (`recent`: the conversation just before it, for follow-ups), or None."""
    prompt = f"Today: {today}.\n"
    if recent:
        prompt += f"The conversation just before (for context):\n{recent}\n\n"
    prompt += f"Request from the owner: {request}"
    plan = heavy_model.ask(prompt, "plan", schema=SCHEMA, system=PLANNER + catalog(tools))
    return check(plan, {t["function"]["name"] for t in tools})


def step_tools(step, names, last=False):
    """The tool names a step may use: its own and their group mates. A step that named none gets all of them,
    except the last one: that one only answers from what the steps found (with every tool the 4b checked a
    folder again, saw the file its own step 2 had written and said it was already there, 2026-11-06)."""
    own = set(step["tools"]) & set(names)
    if not own:
        return set() if last else set(names)
    chosen = set(own)
    for group in GROUPS:
        if group & own:
            chosen |= group
    return chosen & set(names)


def plan_text(steps):
    return "\n".join(f"{i}) {s['do']}" for i, s in enumerate(steps, 1))


def results_text(results):
    return "\n".join(f"Step {i}: {r}" for i, r in enumerate(results, 1)) or "(nothing yet)"


def step_prompt(request, steps, index, results):
    """What the 4b sees for step `index` (0-based)."""
    step = steps[index]
    last = index == len(steps) - 1
    return (f"You are doing one step of a plan for the user's request.\n"
            f"Request: {request}\n"
            f"Plan:\n{plan_text(steps)}\n"
            f"Done so far:\n{results_text(results)}\n\n"
            f"Now do step {index + 1} of {len(steps)}: {step['do']}\n"
            + (f"It worked if: {step['check']}\n" if step["check"] else "")
            + "Use the tools for this step only; don't do later steps. Something is done only when a tool did it. "
            + ("This is the last step: answer the user directly, short and plain, with the result they asked for. "
               "'Done so far' is what you already did in this request; report it as done."
               if last else
               "When it is done (or can't be done), answer in one or two sentences: what happened, and what the "
               "next steps need (file paths, links, names, numbers)."))


def skipped(step, calls):
    """The step named tools and the 4b called none of them: it said the step was done without doing it
    (2026-11-06: "I've written sehirler.txt" with no write_file call, twice in four runs)."""
    own = set(step["tools"])
    return bool(own) and not own & {name for name, _ in calls}


def not_done(step):
    """The one nudge after `skipped`."""
    return (f"You didn't call {', '.join(step['tools'])} in this step, so nothing was done yet. Do the step now "
            "with the tool, or say plainly that you couldn't and why.")


def failed(answer):
    """The 4b's answer to a step says it couldn't do it (or it gave none)."""
    if not answer or not answer.strip():
        return True
    return bool(FAILED.search(re.split(r"[.;:!?\n]", answer.strip(), maxsplit=1)[0]))


def fix(request, steps, index, results, what, tools):
    """A new attempt at step `index` from the heavy model: (step, None), or (None, why it gave up)."""
    names = {t["function"]["name"] for t in tools}
    answer = heavy_model.ask(
        FIX_PROMPT.format(request=request, plan=plan_text(steps), results=results_text(results),
                          step=f"{index + 1}) {steps[index]['do']}", what=what[:1500],
                          failed="It answered that it couldn't." if what else "It gave no answer."),
        "fix", schema=FIX_SCHEMA, system=PLANNER + catalog(tools))
    if not isinstance(answer, dict):
        return None, None
    if answer.get("give_up"):
        return None, str(answer.get("why") or "").strip() or None
    step = {"do": str(answer.get("do", "")).strip(),
            "tools": [t for t in answer.get("tools") or [] if t in names],
            "check": steps[index]["check"], "irreversible": steps[index]["irreversible"]}
    return (step, None) if step["do"] else (None, None)


def short(answer):
    answer = " ".join(str(answer or "").split())
    return answer if len(answer) <= RESULT_CHARS else answer[:RESULT_CHARS] + "..."


def dumps(plan):
    return json.dumps(plan, ensure_ascii=False)
