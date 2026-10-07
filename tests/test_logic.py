"""Checks of the island's logic that need no screen, no network and no permissions.

Run:  .venv/bin/python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import backgrounds          # noqa: E402
import custom_buttons       # noqa: E402
import focus                # noqa: E402
import monitors             # noqa: E402
import screen               # noqa: E402
import settings             # noqa: E402
import updater              # noqa: E402
import version              # noqa: E402


class Stub:
    """Temporarily replace an attribute, restoring it afterwards."""

    def __init__(self, owner, name, value):
        self.owner, self.name, self.value = owner, name, value

    def __enter__(self):
        self.saved = getattr(self.owner, self.name)
        setattr(self.owner, self.name, self.value)

    def __exit__(self, *exc):
        setattr(self.owner, self.name, self.saved)


def fake_run(stdout):
    return lambda *args, **kwargs: SimpleNamespace(stdout=stdout, returncode=0, stderr="")


class VersionTests(unittest.TestCase):
    def test_repository_version_is_a_plain_number(self):
        self.assertIsNotNone(updater.parse(version.VERSION))

    def test_parse(self):
        self.assertEqual(updater.parse("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse("1.10"), (1, 10))
        self.assertIsNone(updater.parse("v1.2-beta"))
        self.assertIsNone(updater.parse("release"))
        self.assertIsNone(updater.parse(None))

    def test_is_newer(self):
        self.assertTrue(updater.is_newer("v1.2.0", "1.1.9"))
        self.assertTrue(updater.is_newer("v1.10", "1.9.5"))       # numeric, not alphabetical
        self.assertFalse(updater.is_newer("v1.0", "1.0.0"))       # same version, different length
        self.assertFalse(updater.is_newer("v0.9", "1.0"))
        self.assertFalse(updater.is_newer("nonsense", "1.0"))


class UpdaterTests(unittest.TestCase):
    def release(self, **changes):
        name = "Dynamic-Island-9.9.9.pkg"
        data = {"tag_name": "v9.9.9", "assets": [
            {"name": name, "browser_download_url": updater.DOWNLOAD_PREFIX + "v9.9.9/" + name},
            {"name": name + ".sha256", "browser_download_url": updater.DOWNLOAD_PREFIX + "v9.9.9/" + name + ".sha256"}]}
        data.update(changes)
        return lambda *a, **k: json.dumps(data).encode()

    def test_finds_a_newer_release(self):
        with Stub(updater, "_curl", self.release()):
            info = updater.Updater(lambda: True)._find_newer()
        self.assertEqual(info["version"], "9.9.9")
        self.assertTrue(info["url"].startswith(updater.DOWNLOAD_PREFIX))
        self.assertTrue(info["sha_url"].endswith(".pkg.sha256"))

    def test_ignores_prereleases_drafts_and_old_versions(self):
        for changes in ({"prerelease": True}, {"draft": True}, {"tag_name": "v0.0.0"}, {"tag_name": "latest"}):
            with Stub(updater, "_curl", self.release(**changes)):
                self.assertIsNone(updater.Updater(lambda: True)._find_newer(), changes)

    def test_waits_until_the_installer_is_attached(self):
        with Stub(updater, "_curl", self.release(assets=[])):
            self.assertIsNone(updater.Updater(lambda: True)._find_newer())

    def test_no_release_yet_is_not_an_error(self):
        def missing(*a, **k):
            raise RuntimeError("curl: (22) The requested URL returned error: 404")
        with Stub(updater, "_curl", missing):
            self.assertIsNone(updater.Updater(lambda: True)._find_newer())

    def test_refuses_downloads_from_anywhere_else(self):
        info = {"name": "x.pkg", "url": "https://example.com/x.pkg", "sha_url": None}
        with self.assertRaises(RuntimeError):
            updater.Updater(lambda: True)._download(info)

    def test_development_builds_never_update(self):
        self.assertFalse(updater.can_update())


class FocusTests(unittest.TestCase):
    def app(self, bundle_id, pid=1, policy=0):
        return SimpleNamespace(bundleIdentifier=lambda: bundle_id, processIdentifier=lambda: pid,
                               activationPolicy=lambda: policy, localizedName=lambda: bundle_id)

    def test_clean_site(self):
        self.assertEqual(focus.clean_site("https://www.YouTube.com/watch?v=1"), "youtube.com")
        self.assertEqual(focus.clean_site("  bilibili.com "), "bilibili.com")
        self.assertEqual(focus.clean_site(""), "")

    def test_blacklist_sites(self):
        guard, mode = focus.Guard(), {"block": focus.BLACKLIST, "sites": ["youtube.com"]}
        self.assertTrue(guard.site_blocked("https://www.youtube.com/watch", mode))
        self.assertTrue(guard.site_blocked("https://m.youtube.com/", mode))
        self.assertFalse(guard.site_blocked("https://notyoutube.com/", mode))
        self.assertFalse(guard.site_blocked("https://github.com", mode))

    def test_whitelist_sites(self):
        guard, mode = focus.Guard(), {"block": focus.WHITELIST, "sites": ["github.com"]}
        self.assertFalse(guard.site_blocked("https://github.com/x", mode))
        self.assertTrue(guard.site_blocked("https://youtube.com", mode))

    def test_pages_that_are_not_websites_are_never_blocked(self):
        guard, mode = focus.Guard(), {"block": focus.WHITELIST, "sites": []}
        for url in ("about:blank", "file:///tmp/blocked.html", "favorites://", ""):
            self.assertFalse(guard.site_blocked(url, mode), url)

    def test_blacklist_apps(self):
        guard, mode = focus.Guard(), {"block": focus.BLACKLIST, "apps": [{"id": "com.example.game"}]}
        self.assertTrue(guard.app_blocked(self.app("com.example.game"), mode))
        self.assertFalse(guard.app_blocked(self.app("com.example.editor"), mode))

    def test_whitelist_apps(self):
        guard, mode = focus.Guard(), {"block": focus.WHITELIST, "apps": [{"id": "com.example.editor"}]}
        self.assertFalse(guard.app_blocked(self.app("com.example.editor"), mode))
        self.assertTrue(guard.app_blocked(self.app("com.example.game"), mode))

    def test_the_island_and_system_apps_are_never_blocked(self):
        guard = focus.Guard()
        everything = {"block": focus.WHITELIST, "apps": []}
        listed = {"block": focus.BLACKLIST, "apps": [{"id": "com.dynamicisland.app"}, {"id": "com.apple.finder"}]}
        for mode in (everything, listed):
            self.assertFalse(guard.app_blocked(self.app("com.dynamicisland.app"), mode))
            self.assertFalse(guard.app_blocked(self.app("com.apple.finder"), mode))
            self.assertFalse(guard.app_blocked(self.app("com.example.x", pid=os.getpid()), mode))
        self.assertFalse(guard.app_blocked(self.app("com.example.agent", policy=1), everything))   # no Dock icon

    def test_describe(self):
        self.assertIn("no blocking", focus.describe({"minutes": 25, "block": focus.BLACKLIST}))
        self.assertIn("blocks 2", focus.describe({"block": focus.BLACKLIST, "apps": [{}], "sites": ["a.com"]}))
        self.assertIn("allows only 1", focus.describe({"block": focus.WHITELIST, "sites": ["a.com"]}))


class SettingsTests(unittest.TestCase):
    def load(self, content):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            if content is not None:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            with Stub(settings, "PATH", path):
                return settings.load()

    def test_defaults_when_there_is_no_file(self):
        values = self.load(None)
        self.assertEqual(set(values), set(settings.DEFAULTS))
        self.assertTrue(values["focus_modes"])                      # filled with the built-in modes

    def test_saved_values_win_and_bad_ones_are_ignored(self):
        values = self.load(json.dumps({"glow": False, "clock24": "yes", "unknown": 1, "background_dim": 0.62}))
        self.assertFalse(values["glow"])
        self.assertIs(values["clock24"], True)                      # wrong type: default kept
        self.assertNotIn("unknown", values)
        self.assertEqual(values["background_dim"], 0.62)

    def test_broken_file_falls_back_to_defaults(self):
        self.assertEqual(self.load("{not json")["glow"], settings.DEFAULTS["glow"])

    def test_lists_are_not_shared_between_loads(self):
        first, second = self.load(None), self.load(None)
        first["custom_buttons"].append({"name": "x"})
        self.assertEqual(second["custom_buttons"], [])

    def test_non_ascii_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            with Stub(settings, "PATH", os.path.join(folder, "settings.json")):
                values = settings.load()
                values["custom_buttons"] = [{"name": "打开邮箱", "icon": "star.fill", "kind": "url", "target": "x.com"}]
                settings.save(values)
                self.assertEqual(settings.load()["custom_buttons"][0]["name"], "打开邮箱")


class MonitorTests(unittest.TestCase):
    def test_battery(self):
        text = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t87%; charging; 0:30 remaining\n"
        with Stub(monitors.subprocess, "run", fake_run(text)):
            self.assertEqual(monitors.battery(), (87, True))
        with Stub(monitors.subprocess, "run", fake_run("Now drawing from 'Battery Power'\n -x\t9%; discharging\n")):
            self.assertEqual(monitors.battery(), (9, False))

    def test_bluetooth_with_non_ascii_names(self):
        data = {"SPBluetoothDataType": [{"device_connected": [
            {"Logi M750": {"device_minorType": "Mouse"}},
            {"HFY的耳机": {"device_batteryLevelMain": "80%"}}]}]}
        with Stub(monitors.subprocess, "run", fake_run(json.dumps(data, ensure_ascii=False))):
            self.assertEqual(monitors.bluetooth(), {"Logi M750": None, "HFY的耳机": "80%"})
        with Stub(monitors.subprocess, "run", fake_run(json.dumps({"SPBluetoothDataType": [{}]}))):
            self.assertEqual(monitors.bluetooth(), {})

    def test_gpu(self):
        with Stub(monitors.subprocess, "run", fake_run('"Device Utilization %"=30,"x"=1\n"Device Utilization %" = 72')):
            self.assertEqual(monitors.gpu_usage(), 0.72)            # the busiest GPU
        with Stub(monitors.subprocess, "run", fake_run("nothing here")):
            self.assertIsNone(monitors.gpu_usage())

    def test_system_now_playing(self):
        reading = {"now": 1000.0, "app": "Browser", "bundle": "com.example.browser", "title": "Song",
                   "artist": None, "rate": 1, "elapsed": 10.0, "duration": 200.0, "stamp": 990.0}
        with Stub(monitors.subprocess, "run", fake_run(json.dumps(reading))):
            item = monitors.system_now_playing()
        self.assertEqual((item["title"], item["artist"], item["app"]), ("Song", "", "Browser"))
        self.assertTrue(item["playing"])
        self.assertEqual(item["control"], monitors.SYSTEM)
        self.assertAlmostEqual(item["position"], 20.0)              # 10 s elapsed + 10 s since the timestamp
        with Stub(monitors.subprocess, "run", fake_run(json.dumps({"now": 1.0}))):
            self.assertIsNone(monitors.system_now_playing())        # nothing playing
        with Stub(monitors.subprocess, "run", fake_run("")):
            self.assertIsNone(monitors.system_now_playing())        # the interface said nothing at all

    def test_stale_paused_items_are_dropped(self):
        paused = {"now": 1000.0, "title": "Song", "rate": 0, "elapsed": 5.0, "duration": 200.0}
        with Stub(monitors.subprocess, "run", fake_run(json.dumps(dict(paused, stamp=990.0)))):
            self.assertIsNotNone(monitors.now_playing())
        with Stub(monitors.subprocess, "run", fake_run(json.dumps(dict(paused, stamp=1000.0 - 2 * monitors.STALE_PAUSE)))):
            self.assertIsNone(monitors.now_playing())

    def test_position_now(self):
        now = time.time()
        playing = {"playing": True, "rate": 1.0, "position": 30.0, "duration": 100.0, "at": now - 5}
        self.assertAlmostEqual(monitors.position_now(playing), 35.0, delta=0.5)
        self.assertEqual(monitors.position_now(dict(playing, playing=False)), 30.0)
        self.assertEqual(monitors.position_now(dict(playing, at=now - 500)), 100.0)     # never past the end
        self.assertEqual(monitors.position_now({"playing": True, "duration": 0}), 0.0)
        self.assertEqual(monitors.position_now(None), 0.0)


class ScreenTests(unittest.TestCase):
    def display(self, number):
        return SimpleNamespace(deviceDescription=lambda: {"NSScreenNumber": number})

    def test_only_the_built_in_display_is_chosen(self):
        screens = [self.display(5), self.display(1)]
        self.assertIs(screen.builtin_screen(screens, lambda n: n == 1), screens[1])

    def test_no_built_in_display(self):
        self.assertIsNone(screen.builtin_screen([self.display(5)], lambda n: False))
        self.assertIsNone(screen.builtin_screen([], lambda n: True))


class SmallThingsTests(unittest.TestCase):
    def test_background_dimming_cycles(self):
        levels = [value for value, _ in backgrounds.DIM_CHOICES]
        seen, value = [], levels[0]
        for _ in levels:
            value = backgrounds.next_dim(value)
            seen.append(value)
        self.assertEqual(sorted(seen), sorted(levels))
        self.assertEqual(backgrounds.dim_label(0.44), "Medium")

    def test_background_choice_cycles_and_recovers(self):
        with Stub(backgrounds, "presets", lambda: [("A", "/a"), ("B", "/b")]):
            values = {"background": "", "background_custom": ""}
            order = []
            for _ in range(3):
                values["background"] = backgrounds.next_choice(values)
                order.append(values["background"])
            self.assertEqual(order, ["A", "B", ""])
            self.assertEqual(backgrounds.next_choice({"background": "Gone", "background_custom": ""}), "")
            self.assertEqual(backgrounds.path_for({"background": "B", "background_custom": ""}), "/b")

    def test_custom_button_description(self):
        self.assertEqual(custom_buttons.describe({"kind": "app", "target": "/Applications/Safari.app"}),
                         "Open App  ·  Safari")
        self.assertEqual(custom_buttons.describe({"kind": "url", "target": "github.com"}),
                         "Open Website  ·  github.com")


if __name__ == "__main__":
    unittest.main()
