"""Self-update from GitHub releases.

Asks GitHub for the release marked "Latest". If its tag is a higher version than this app, the
installer attached to it is downloaded, checked and opened; the installer itself quits the old copy
and starts the new one. Everything goes through /usr/bin/curl, so macOS's own certificates and
proxy settings apply.
"""
import hashlib
import json
import os
import re
import subprocess
import threading
import time

from Foundation import NSBundle

from version import VERSION

REPO = "TonyD365/Mac-Dynamic-Island"
LATEST_URL = "https://api.github.com/repos/%s/releases/latest" % REPO
# Only files served from this repository's own releases are ever downloaded.
DOWNLOAD_PREFIX = "https://github.com/%s/releases/download/" % REPO
CACHE = os.path.expanduser("~/Library/Caches/DynamicIsland")
CHECK_EVERY = 3600          # look for a new release once an hour
FIRST_CHECK_AFTER = 20


def parse(text):
    """'v1.2.3' or '1.2.3' -> (1, 2, 3); None if it isn't a plain version number."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def is_newer(candidate, current):
    a, b = parse(candidate), parse(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def can_update():
    """Only a released, packaged app updates itself; development runs never do."""
    bundle = NSBundle.mainBundle()
    packaged = (bundle.bundlePath() or "").endswith(".app") and bundle.bundleIdentifier() != "org.python.python"
    return packaged and parse(VERSION) not in (None, (0, 0, 0))


def _curl(*args, timeout=60):
    result = subprocess.run(["/usr/bin/curl", "--fail", "--silent", "--show-error", "--location",
                             "--proto", "=https", "--proto-redir", "=https", *args],
                            capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or "download failed")
    return result.stdout


class Updater:
    """state: idle -> checking -> current | available -> downloading -> ready | failed"""

    def __init__(self, automatic):
        self.automatic = automatic      # callable: download and install without being asked?
        self.state = "idle"
        self.latest = None              # version string of the newer release
        self.package = None             # path of the downloaded, verified installer
        self.error = None
        self.manual = False             # the last check was asked for by the user
        self._info = None
        self._lock = threading.Lock()

    def start(self):
        if can_update():
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        time.sleep(FIRST_CHECK_AFTER)
        while True:
            self.check(manual=False)
            time.sleep(CHECK_EVERY)

    def check_now(self):
        """The user asked: look for an update, and fetch it if there is one."""
        threading.Thread(target=self.check, kwargs={"manual": True}, daemon=True).start()

    def check(self, manual):
        if not self._lock.acquire(blocking=False):
            return                      # a check or download is already running
        try:
            self.manual = manual
            if self.state == "ready" and self.package and os.path.exists(self.package):
                return
            self.state, self.error = "checking", None
            info = self._find_newer()
            if info is None:
                self.state = "current"
                return
            self._info, self.latest = info, info["version"]
            self.state = "available"
            if manual or self.automatic():
                self.state = "downloading"
                self.package = self._download(info)
                self.state = "ready"
        except Exception as e:
            self.error = str(e)
            self.state = "failed"
        finally:
            self._lock.release()

    def _find_newer(self):
        try:
            raw = _curl("--max-time", "20", "-H", "Accept: application/vnd.github+json",
                        "-H", "User-Agent: Dynamic-Island-Updater", LATEST_URL, timeout=30)
        except RuntimeError as e:
            if "404" in str(e):         # the repository has no published release yet
                return None
            raise
        release = json.loads(raw.decode("utf-8", "replace"))
        tag = release.get("tag_name", "")
        if release.get("draft") or release.get("prerelease") or not is_newer(tag, VERSION):
            return None
        urls = {a.get("name", ""): a.get("browser_download_url", "") for a in release.get("assets", [])}
        package = next((n for n in urls if n.endswith(".pkg")), None)
        if package is None:
            return None                 # the build hasn't been attached yet; try again next time
        return {"version": tag.lstrip("v"), "name": package, "url": urls[package],
                "sha_url": urls.get(package + ".sha256")}

    def _download(self, info):
        for url in (info["url"], info["sha_url"]):
            if url and not url.startswith(DOWNLOAD_PREFIX):
                raise RuntimeError("unexpected download address")
        os.makedirs(CACHE, exist_ok=True)
        for old in os.listdir(CACHE):
            if old.endswith((".pkg", ".part")):
                os.remove(os.path.join(CACHE, old))
        path = os.path.join(CACHE, os.path.basename(info["name"]))
        _curl("--max-time", "600", "-o", path + ".part", info["url"], timeout=660)
        with open(path + ".part", "rb") as f:
            data = f.read()
        if data[:4] != b"xar!":         # every .pkg starts with this
            raise RuntimeError("the download is not an installer package")
        if info["sha_url"]:
            expected = _curl("--max-time", "20", info["sha_url"], timeout=30).decode("ascii", "replace").split()
            if not expected or hashlib.sha256(data).hexdigest() != expected[0].lower():
                raise RuntimeError("the download failed its checksum")
        os.replace(path + ".part", path)
        return path

    def install(self):
        """Hand the verified package to the macOS Installer."""
        if self.state == "ready" and self.package and os.path.exists(self.package):
            subprocess.Popen(["/usr/bin/open", self.package])
            return True
        return False
