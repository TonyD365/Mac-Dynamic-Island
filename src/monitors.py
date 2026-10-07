"""Background polling of camera / microphone / power / now-playing state.

Camera and microphone are only queried for "is some process using it"; the
devices themselves are never opened, so no camera/mic permission is needed.
"""
import ctypes
import json
import os
import re
import subprocess
import threading
import time

from AppKit import NSRunningApplication

import calendar_events


class _Addr(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]


def _fourcc(s):
    return int.from_bytes(s.encode(), "big")


_SYSTEM_OBJECT = 1
_DEVICES = _fourcc("dev#")
_RUNNING_SOMEWHERE = _fourcc("gone")
_STREAMS = _fourcc("stm#")
_GLOBAL = _fourcc("glob")
_INPUT = _fourcc("inpt")

_cmio = ctypes.CDLL("/System/Library/Frameworks/CoreMediaIO.framework/CoreMediaIO")
_audio = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")


def _cmio_get(obj, selector, ctype, count=1):
    addr = _Addr(selector, _GLOBAL, 0)
    buf = (ctype * count)()
    used = ctypes.c_uint32(0)
    err = _cmio.CMIOObjectGetPropertyData(
        ctypes.c_uint32(obj), ctypes.byref(addr), 0, None,
        ctypes.c_uint32(ctypes.sizeof(buf)), ctypes.byref(used), buf)
    return None if err else list(buf)[: used.value // ctypes.sizeof(ctype)]


def _cmio_size(obj, selector):
    addr = _Addr(selector, _GLOBAL, 0)
    size = ctypes.c_uint32(0)
    err = _cmio.CMIOObjectGetPropertyDataSize(ctypes.c_uint32(obj), ctypes.byref(addr), 0, None, ctypes.byref(size))
    return 0 if err else size.value


def camera_in_use():
    n = _cmio_size(_SYSTEM_OBJECT, _DEVICES) // 4
    if not n:
        return False
    for dev in _cmio_get(_SYSTEM_OBJECT, _DEVICES, ctypes.c_uint32, n) or []:
        v = _cmio_get(dev, _RUNNING_SOMEWHERE, ctypes.c_uint32)
        if v and v[0]:
            return True
    return False


def _audio_size(obj, selector, scope=_GLOBAL):
    addr = _Addr(selector, scope, 0)
    size = ctypes.c_uint32(0)
    err = _audio.AudioObjectGetPropertyDataSize(ctypes.c_uint32(obj), ctypes.byref(addr), 0, None, ctypes.byref(size))
    return 0 if err else size.value


def _audio_get(obj, selector, count=1):
    addr = _Addr(selector, _GLOBAL, 0)
    buf = (ctypes.c_uint32 * count)()
    size = ctypes.c_uint32(ctypes.sizeof(buf))
    err = _audio.AudioObjectGetPropertyData(ctypes.c_uint32(obj), ctypes.byref(addr), 0, None, ctypes.byref(size), buf)
    return None if err else list(buf)[: size.value // 4]


def mic_in_use():
    n = _audio_size(_SYSTEM_OBJECT, _DEVICES) // 4
    if not n:
        return False
    for dev in _audio_get(_SYSTEM_OBJECT, _DEVICES, n) or []:
        if _audio_size(dev, _STREAMS, _INPUT) == 0:  # output-only device
            continue
        v = _audio_get(dev, _RUNNING_SOMEWHERE)
        if v and v[0]:
            return True
    return False


_DEFAULT_OUTPUT = _fourcc("dOut")
_VOLUME = _fourcc("vmvc")
_MUTE = _fourcc("mute")
_OUTPUT = _fourcc("outp")


def _output_prop(selector, ctype, value=None):
    """Read (value=None) or write a property of the current output device."""
    dev = _audio_get(_SYSTEM_OBJECT, _DEFAULT_OUTPUT)
    if not dev or not dev[0]:
        return None
    addr = _Addr(selector, _OUTPUT, 0)
    if value is None:
        v = ctype()
        size = ctypes.c_uint32(ctypes.sizeof(v))
        err = _audio.AudioObjectGetPropertyData(ctypes.c_uint32(dev[0]), ctypes.byref(addr), 0, None,
                                                ctypes.byref(size), ctypes.byref(v))
        return None if err else v.value
    v = ctype(value)
    return not _audio.AudioObjectSetPropertyData(ctypes.c_uint32(dev[0]), ctypes.byref(addr), 0, None,
                                                 ctypes.c_uint32(ctypes.sizeof(v)), ctypes.byref(v))


def volume():
    return _output_prop(_VOLUME, ctypes.c_float)


def muted():
    v = _output_prop(_MUTE, ctypes.c_uint32)
    return None if v is None else bool(v)


def set_volume(level):
    _output_prop(_VOLUME, ctypes.c_float, max(0.0, min(1.0, level)))


def set_mute(on):
    _output_prop(_MUTE, ctypes.c_uint32, 1 if on else 0)


try:
    _display_services = ctypes.CDLL("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices")
except OSError:
    _display_services = None


def brightness(display):
    """Brightness of the given display, 0..1, or None."""
    if _display_services is None or not display:
        return None
    level = ctypes.c_float()
    if _display_services.DisplayServicesGetBrightness(ctypes.c_uint32(display), ctypes.byref(level)) != 0:
        return None
    return level.value


def bluetooth():
    """Connected Bluetooth devices: {name: battery text or None}."""
    out = subprocess.run(["system_profiler", "SPBluetoothDataType", "-json"],
                         capture_output=True, encoding="utf-8", errors="replace", timeout=10).stdout
    devices = {}
    for entry in json.loads(out)["SPBluetoothDataType"][0].get("device_connected", []):
        for name, info in entry.items():
            devices[name] = (info.get("device_batteryLevelMain") or info.get("device_batteryLevelLeft")
                             or info.get("device_batteryLevelCase"))
    return devices


_libc = ctypes.CDLL(None)
_libc.mach_host_self.restype = ctypes.c_uint32
_host = _libc.mach_host_self()


def _cpu_ticks():
    ticks = (ctypes.c_uint32 * 4)()      # user, system, idle, nice
    count = ctypes.c_uint32(4)
    err = _libc.host_statistics(ctypes.c_uint32(_host), 3, ticks, ctypes.byref(count))
    return None if err else list(ticks)


def gpu_usage():
    """How busy the GPU is, 0..1 (the busiest one if there are several), or None if macOS doesn't say."""
    out = subprocess.run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"],
                         capture_output=True, encoding="utf-8", errors="replace", timeout=3).stdout
    values = [int(v) for v in re.findall(r'"Device Utilization %"\s*=\s*(\d+)', out)]
    return min(1.0, max(values) / 100.0) if values else None


def memory_used():
    """Fraction of physical memory in use (active + wired + compressed)."""
    out = subprocess.run(["vm_stat"], capture_output=True, encoding="utf-8", errors="replace", timeout=3).stdout
    page = int(re.search(r"page size of (\d+)", out).group(1))
    used = sum(int(n) for n in re.findall(r"Pages (?:active|wired down|occupied by compressor):\s+(\d+)", out))
    return used * page / (os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))


def battery():
    """Return (percent or None, on_ac)."""
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, encoding="utf-8", errors="replace", timeout=3).stdout
    except Exception:
        return None, None
    m = re.search(r"(\d+)%", out)
    return (int(m.group(1)) if m else None), "AC Power" in out


_PLAYERS = (("Music", "com.apple.Music"), ("Spotify", "com.spotify.client"))
_SCRIPT = '''tell application "%s"
    if player state is stopped then return ""
    return (player state as string) & linefeed & (name of current track) & linefeed & (artist of current track)
end tell'''


# What macOS itself lists as "Now Playing" (any app: browsers, music and video players). The
# framework refuses ordinary apps, so the question is put through osascript, which it accepts.
# Undocumented; if it ever stops answering, now_playing() falls back to asking the players.
_MEDIA_REMOTE = '''ObjC.import("Foundation");
  $.NSBundle.bundleWithPath("/System/Library/PrivateFrameworks/MediaRemote.framework/").load;'''

_SYSTEM_SCRIPT = '''function run() {
  %s
  const Req = $.NSClassFromString("MRNowPlayingRequest");
  const out = {now: Date.now() / 1000};
  try {
    const client = Req.localNowPlayingPlayerPath.client;
    out.app = ObjC.unwrap(client.displayName);
    out.bundle = ObjC.unwrap(client.bundleIdentifier);
  } catch (e) {}
  try {
    const info = Req.localNowPlayingItem.nowPlayingInfo;
    const get = key => ObjC.unwrap(info.valueForKey("kMRMediaRemoteNowPlayingInfo" + key));
    out.title = get("Title");
    out.artist = get("Artist");
    out.rate = get("PlaybackRate");
    out.elapsed = get("ElapsedTime");
    out.duration = get("Duration");
    const stamp = get("Timestamp");
    out.stamp = stamp ? stamp.getTime() / 1000 : null;
  } catch (e) {}
  return JSON.stringify(out);
}''' % _MEDIA_REMOTE

# The helper has to stay alive for a moment after the call, or the request never leaves it.
_COMMAND_SCRIPT = '''function run(argv) {
  %s
  if (argv[0] == "seek") {
    ObjC.bindFunction("MRMediaRemoteSetElapsedTime", ["void", ["double"]]);
    $.MRMediaRemoteSetElapsedTime(parseFloat(argv[1]));
  } else {
    ObjC.bindFunction("MRMediaRemoteSendCommand", ["bool", ["unsigned int", "id"]]);
    $.MRMediaRemoteSendCommand(parseInt(argv[1]), $.NSDictionary.dictionary);
  }
  $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.4));
}''' % _MEDIA_REMOTE

SYSTEM = "system"            # value of 'control' for items driven through the system-wide interface
_SYSTEM_COMMANDS = {"playpause": 2, "next track": 4, "previous track": 5}
STALE_PAUSE = 300            # a paused item nobody has touched for this long is dropped


def system_now_playing():
    """The system-wide Now Playing item, or None if there is none (or macOS won't say)."""
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", _SYSTEM_SCRIPT], capture_output=True,
                         encoding="utf-8", errors="replace", timeout=10).stdout
    try:
        data = json.loads(out)
    except ValueError:
        return None
    title = data.get("title")
    if not title:
        return None
    number = lambda key: float(data[key]) if isinstance(data.get(key), (int, float)) else 0.0
    rate, stamp, now = number("rate"), number("stamp"), number("now")
    position = number("elapsed") + (max(0.0, now - stamp) * rate if stamp else 0.0)
    return {"app": data.get("app") or "", "control": SYSTEM, "playing": rate > 0, "rate": rate,
            "title": str(title), "artist": str(data.get("artist") or ""),
            "position": position, "duration": number("duration"), "at": time.time(),
            "idle": (now - stamp) if (stamp and rate == 0) else 0.0}


def now_playing():
    """Return what is playing, or None. Never launches a player.

    Keys: app, control (how to send commands: SYSTEM, a player's name, or None), playing, title,
    artist; and for system items rate, position and duration in seconds, and 'at' (when it was read).
    """
    try:
        current = system_now_playing()
    except Exception:
        current = None
    if current is not None:
        return None if current["idle"] > STALE_PAUSE else current
    return players_now_playing()


def position_now(item):
    """Where playback is at this moment, extrapolated from the last reading."""
    if not item or not item.get("duration"):
        return 0.0
    position = item.get("position", 0.0)
    if item.get("playing"):
        position += (time.time() - item.get("at", time.time())) * item.get("rate", 1.0)
    return max(0.0, min(item["duration"], position))


def _media_remote(*args):
    subprocess.Popen(["osascript", "-l", "JavaScript", "-e", _COMMAND_SCRIPT, *[str(a) for a in args]],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def media_command(item, command):
    """Send 'playpause', 'next track' or 'previous track' to whatever is playing."""
    if item.get("control") == SYSTEM:
        _media_remote("command", _SYSTEM_COMMANDS[command])
    elif item.get("control"):
        player_command(item["control"], command)


def media_seek(seconds):
    _media_remote("seek", "%.2f" % seconds)


def players_now_playing():
    """Ask Music and Spotify directly: the fallback when the system-wide list is unavailable."""
    best = None
    for app, bundle_id in _PLAYERS:
        if not NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id):
            continue
        try:
            out = subprocess.run(["osascript", "-e", _SCRIPT % app], capture_output=True, encoding="utf-8", errors="replace", timeout=20).stdout
        except Exception:
            continue
        parts = out.strip("\n").split("\n")
        if len(parts) < 3:
            continue
        info = {"app": app, "control": app, "playing": parts[0] == "playing", "title": parts[1],
                "artist": parts[2]}
        if info["playing"]:
            return info
        best = best or info
    return best


def player_command(app, command):
    subprocess.Popen(["osascript", "-e", 'tell application "%s" to %s' % (app, command)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Monitors:
    def __init__(self):
        self.cam = False
        self.mic = False
        self.batt = None
        self.ac = None
        self.music = None
        self.music_hold = 0.0    # ignore readings until then: a command was just sent
        self.calendar = calendar_events.Calendar()
        self.calendar_on = False # set by the island from the Calendar Events setting
        self.event = None        # the next calendar event, when switched on and allowed
        self.errors = {}         # monitor name -> last failure
        self.volume = None
        self.muted = None
        self.brightness = None
        self.bt = None           # None until the first scan
        self.display_id = None   # built-in display, set by the island once it has found it
        self.cpu = None
        self.gpu = None
        self.mem = None
        self._ticks = None

    def start(self):
        self._spawn(self._devices, 1.0)
        self._spawn(self._power, 4.0)
        self._spawn(self._music, 1.5)
        self._spawn(self._levels, 0.12)
        self._spawn(self._bluetooth, 1.0)    # frequent: a device can drop and rejoin within a couple of seconds
        self._spawn(self._stats, 3.0)
        self._spawn(self._calendar, 30.0)

    def _spawn(self, fn, interval):
        def loop():
            while True:
                try:
                    fn()
                    self.errors.pop(fn.__name__, None)
                except Exception as e:      # keep the reason; shown by the diagnostics dump
                    self.errors[fn.__name__] = repr(e)
                time.sleep(interval)
        threading.Thread(target=loop, daemon=True).start()

    def _devices(self):
        self.cam = camera_in_use()
        self.mic = mic_in_use()

    def _power(self):
        self.batt, self.ac = battery()

    def _music(self):
        reading = now_playing()
        if time.time() >= self.music_hold:      # otherwise a stale reading would undo the UI's own update
            self.music = reading

    def _levels(self):
        self.volume = volume()
        self.muted = muted()
        self.brightness = brightness(self.display_id)

    def _bluetooth(self):
        self.bt = bluetooth()

    def _stats(self):
        ticks = _cpu_ticks()
        if ticks and self._ticks:
            delta = [b - a for a, b in zip(self._ticks, ticks)]
            total = sum(delta)
            if total > 0:
                self.cpu = 1.0 - delta[2] / total
        self._ticks = ticks
        self.mem = memory_used()
        self.gpu = gpu_usage()

    def _calendar(self):
        self.event = self.calendar.next_event() if self.calendar_on else None
