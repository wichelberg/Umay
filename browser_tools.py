"""Tools that let Umay open sites and YouTube videos in Opera GX.

This is the "light" approach: Umay only hands Opera URLs (it opens them in a new tab of
the running window, or starts first). Everything inside pages, the video's loop, volume and
mute included, goes through the Umay Web Control extension (web_control.py). The one key
press left here is YouTube's own "f" for fullscreen (press_fullscreen): browsers allow
fullscreen only after a real key press or click, which an extension can't make.

Opening pages doesn't change anything on the PC, so unlike pc_tools these don't
ask for confirmation.
"""
import ctypes
import ctypes.wintypes as wintypes
import subprocess
import time
import winreg
from urllib.parse import quote_plus, urlparse

from pynput.keyboard import Controller

OPERA_REG_KEY = r"Software\Clients\StartMenuInternet\Opera GXStable\shell\open\command"
OPERA_PROCESS = "opera.exe"
YOUTUBE_RESULTS = 10
FOCUS_WAIT_SECONDS = 0.4
FULLSCREEN_KEY = ("f",)  # YouTube's own shortcut (no extension involved)

_user32 = ctypes.windll.user32
_keyboard = Controller()
_last_results = []  # [(title, url)] from the latest search_youtube


class ToolError(Exception):
    pass


def _opera_exe():
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, OPERA_REG_KEY) as key:
                command = winreg.QueryValueEx(key, "")[0]
        except OSError:
            continue
        return command.split('"')[1] if command.startswith('"') else command.split()[0]
    raise ToolError("Opera GX doesn't seem to be installed.")


def _open(url):
    """Opens url in Opera GX: a new tab if it's running, otherwise it starts with it."""
    if urlparse(url).scheme not in ("http", "https"):
        raise ToolError("Only http(s) web addresses can be opened.")
    subprocess.Popen([_opera_exe(), url])


def _run(fn):
    try:
        return fn()
    except ToolError as e:
        return str(e)
    except OSError as e:
        return f"Failed: {e}"


def open_in_browser(url: str) -> str:
    def run():
        _open(url)
        return f"Opened {url} in Opera GX."
    return _run(run)


def search_youtube(query: str) -> str:
    def run():
        import yt_dlp  # heavy; only load when actually searching

        _open(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
        options = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"ytsearch{YOUTUBE_RESULTS}:{query}", download=False)
        _last_results.clear()
        for entry in info.get("entries") or []:
            if entry.get("id"):
                _last_results.append((entry.get("title") or "?", f"https://www.youtube.com/watch?v={entry['id']}", entry))
        if not _last_results:
            return "Opened the search in Opera GX, but couldn't read any results."
        lines = []
        for i, (title, _, entry) in enumerate(_last_results, 1):
            extra = ", ".join(filter(None, [entry.get("channel"), _duration(entry.get("duration"))]))
            lines.append(f"{i}. {title}" + (f" ({extra})" if extra else ""))
        return (
            "Opened the search in Opera GX. Show the user this numbered list as-is "
            "(they pick by number with open_youtube_result):\n" + "\n".join(lines)
        )
    return _run(run)


def _duration(seconds):
    if not seconds:
        return ""
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def open_youtube_result(number: int) -> str:
    def run():
        if not _last_results:
            raise ToolError("There's no YouTube search yet. Call search_youtube first.")
        if not 1 <= int(number) <= len(_last_results):
            raise ToolError(f"Pick a number between 1 and {len(_last_results)}.")
        title, url, _ = _last_results[int(number) - 1]
        _open(url)
        return f"Opened #{number}: {title}"
    return _run(run)


# --- keyboard control of the Opera window ----------------------------------------

def _opera_window():
    """The topmost visible Opera GX main window, or None."""
    out = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {OPERA_PROCESS}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout
    pids = {int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"')}
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and _user32.IsWindowVisible(hwnd) and _user32.GetWindowTextLengthW(hwnd):
            if not _user32.GetWindow(hwnd, 4):  # GW_OWNER: skip popups/tooltips
                found.append(hwnd)
                return False  # EnumWindows goes top to bottom; the first one is the front-most
        return True

    _user32.EnumWindows(visit, 0)
    return found[0] if found else None


def _focus(hwnd):
    """Brings hwnd to the front. Windows only lets the foreground app do that, so a
    synthetic Alt press first makes this process count as having had input."""
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    _user32.keybd_event(0x12, 0, 0, 0)  # Alt down
    _user32.keybd_event(0x12, 0, 2, 0)  # Alt up
    _user32.SetForegroundWindow(hwnd)
    time.sleep(FOCUS_WAIT_SECONDS)
    return _user32.GetForegroundWindow() == hwnd


def _press(keys):
    for k in keys:
        _keyboard.press(k)
    for k in reversed(keys):
        _keyboard.release(k)


def _focused_opera():
    hwnd = _opera_window()
    if hwnd is None:
        raise ToolError("Opera GX isn't open.")
    # Never type into another app: only press keys if Opera really is in front.
    if not _focus(hwnd):
        raise ToolError("Couldn't bring Opera GX to the front, so I didn't press anything.")
    return hwnd


def press_fullscreen() -> str:
    """YouTube's "f" in Opera GX's current tab (web_control.control_video's 'fullscreen')."""
    def run():
        _focused_opera()
        _press(FULLSCREEN_KEY)
        return ("Pressed YouTube's fullscreen key (f) in Opera GX's current tab: it toggles fullscreen. "
                "Use look_at_screen to check if needed.")
    return _run(run)


# --- tool schemas ------------------------------------------------------------------

def _tool(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOLS = [
    _tool(
        "open_in_browser",
        "Opens a web page in Opera GX (the user's browser): a new tab if Opera is running, otherwise it starts "
        "Opera with it. Use for 'open X in Opera' / 'open site X'. If the user names a site but you don't know its "
        "exact address, find the best match with web_search first and open that URL.",
        {"url": {"type": "string", "description": "Full http(s) URL, e.g. https://www.youtube.com"}},
        ["url"],
    ),
    _tool(
        "search_youtube",
        "Searches YouTube: opens the results page in Opera GX and returns a numbered list of videos. "
        "Show the user that list so they can pick a video by number.",
        {"query": {"type": "string", "description": "What to search for on YouTube."}},
        ["query"],
    ),
    _tool(
        "open_youtube_result",
        "Opens a video from the latest search_youtube list in Opera GX, by its number in that list.",
        {"number": {"type": "integer", "description": "The video's number in the list (1 = first)."}},
        ["number"],
    ),
]

TOOL_FUNCTIONS = {
    "open_in_browser": open_in_browser,
    "search_youtube": search_youtube,
    "open_youtube_result": open_youtube_result,
}
