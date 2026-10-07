"""Focus modes: a timer plus optional blocking of apps and websites while it runs.

Blocking is a nudge, not a lock: a blocked app is hidden the moment it comes to the front, and a
blocked page in a supported browser is replaced by a "blocked" page. Nothing is quit or deleted,
and stopping the focus session (or quitting the island) lifts it at once.
"""
import html
import os
import subprocess
import threading
import time
from urllib.parse import urlparse

from AppKit import NSApplicationActivationPolicyRegular, NSBundle, NSWorkspace

BLACKLIST, WHITELIST = "blacklist", "whitelist"

DEFAULT_MODES = [
    {"name": "Pomodoro", "minutes": 25, "block": BLACKLIST, "apps": [], "sites": []},
    {"name": "Deep Work", "minutes": 45, "block": BLACKLIST, "apps": [],
     "sites": ["youtube.com", "bilibili.com", "x.com", "twitter.com", "instagram.com", "tiktok.com",
               "reddit.com", "facebook.com"]},
]

# Never blocked, whatever the lists say: the island itself and the pieces of macOS you need to get around.
ALWAYS_ALLOWED = {
    "com.dynamicisland.app", "org.python.python", "com.apple.finder", "com.apple.loginwindow", "com.apple.dock",
    "com.apple.Spotlight", "com.apple.controlcenter", "com.apple.notificationcenterui",
    "com.apple.systemuiserver", "com.apple.systempreferences", "com.apple.SecurityAgent",
}

# Browsers whose current page can be read and changed through AppleScript.
SAFARI = {"com.apple.Safari", "com.apple.SafariTechnologyPreview"}
CHROMIUM = {"com.google.Chrome", "com.microsoft.edgemac", "com.brave.Browser", "company.thebrowser.Browser",
            "com.vivaldi.Vivaldi", "com.operasoftware.Opera", "org.chromium.Chromium"}

BLOCKED_PAGE = os.path.expanduser("~/Library/Application Support/DynamicIsland/blocked.html")


def clean_site(text):
    """'https://www.YouTube.com/watch' -> 'youtube.com'."""
    text = text.strip().lower()
    if not text:
        return ""
    host = urlparse(text if "://" in text else "//" + text).hostname or ""
    return host[4:] if host.startswith("www.") else host


def describe(mode):
    count = len(mode.get("apps", [])) + len(mode.get("sites", []))
    if mode.get("block") == WHITELIST:
        rule = "allows only %d" % count
    else:
        rule = "blocks %d" % count if count else "no blocking"
    return "%d min  ·  %s" % (mode.get("minutes", 25), rule)


def _osascript(script):
    try:
        return subprocess.run(["osascript", "-e", script], capture_output=True, encoding="utf-8",
                              errors="replace", timeout=10).stdout.strip()
    except Exception:
        return ""


class Guard:
    """Enforces the active focus mode. check_apps() must be called regularly on the main thread."""

    def __init__(self):
        self.mode = None
        self.front = None            # bundle id of the frontmost app, for the website thread
        self.blocked = None          # (text, time) of the latest block, for the island to announce
        self._own = {NSBundle.mainBundle().bundleIdentifier(), None}
        self._pid = os.getpid()

    def start(self, mode):
        self.mode = mode
        self._write_blocked_page(mode)
        if mode.get("sites") or mode.get("block") == WHITELIST:
            threading.Thread(target=self._watch_sites, args=(mode,), daemon=True).start()

    def stop(self):
        self.mode = None

    # ---- apps ----

    def app_blocked(self, app, mode):
        bundle_id = app.bundleIdentifier()
        if (bundle_id in self._own or bundle_id in ALWAYS_ALLOWED or app.processIdentifier() == self._pid
                or app.activationPolicy() != NSApplicationActivationPolicyRegular):
            return False
        listed = bundle_id in {a.get("id") for a in mode.get("apps", [])}
        return not listed if mode.get("block") == WHITELIST else listed

    def check_apps(self):
        mode = self.mode
        if mode is None:
            return
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return
        self.front = app.bundleIdentifier()
        if self.app_blocked(app, mode):
            app.hide()
            self.blocked = ("%s is blocked" % (app.localizedName() or "This app"), time.time())

    # ---- websites ----

    def site_blocked(self, url, mode):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False            # new tabs, local files, the blocked page itself
        host = parsed.hostname.lower()
        listed = any(host == s or host.endswith("." + s) for s in mode.get("sites", []))
        return not listed if mode.get("block") == WHITELIST else listed

    def _watch_sites(self, mode):
        target = "file://" + BLOCKED_PAGE.replace(" ", "%20")
        while self.mode is mode:
            front = self.front
            if front in SAFARI:
                page = 'front document'
            elif front in CHROMIUM:
                page = 'active tab of front window'
            else:
                page = None
            if page:
                url = _osascript('tell application id "%s" to return URL of %s' % (front, page))
                if url and self.mode is mode and self.site_blocked(url, mode):
                    _osascript('tell application id "%s" to set URL of %s to "%s"' % (front, page, target))
                    self.blocked = ("%s is blocked" % (urlparse(url).hostname or "This site"), time.time())
            time.sleep(1.2)

    def _write_blocked_page(self, mode):
        try:
            os.makedirs(os.path.dirname(BLOCKED_PAGE), exist_ok=True)
            with open(BLOCKED_PAGE, "w", encoding="utf-8") as f:
                f.write("""<!doctype html><meta charset="utf-8"><title>Blocked</title>
<body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#0b0b14;color:#fff;font-family:-apple-system,sans-serif;text-align:center">
<div><div style="font-size:64px">&#9203;</div><h1 style="font-weight:600">Blocked during focus</h1>
<p style="opacity:.6">%s is running. Stop it from the Dynamic Island to come back here.</p></div>"""
                        % html.escape(mode.get("name", "Focus")))
        except OSError:
            pass
