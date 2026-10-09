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
import calendar_events      # noqa: E402
import custom_buttons       # noqa: E402
import focus                # noqa: E402
import menu                 # noqa: E402
import ring                 # noqa: E402
import shelf                # noqa: E402
import hud_keys             # noqa: E402
import monitors             # noqa: E402
import notifications        # noqa: E402
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


class NewFeatureTests(unittest.TestCase):
    def test_meeting_links_are_found_in_any_field(self):
        link = calendar_events.meeting_link
        self.assertEqual(link("", "Room 4", "Join: https://us02web.zoom.us/j/123456?pwd=abc."),
                         "https://us02web.zoom.us/j/123456?pwd=abc")
        self.assertEqual(link("https://meet.google.com/abc-defg-hij"), "https://meet.google.com/abc-defg-hij")
        self.assertEqual(link("", "<https://teams.microsoft.com/l/meetup-join/19%3a>"),
                         "https://teams.microsoft.com/l/meetup-join/19%3a")
        self.assertIsNone(link("https://example.com/agenda", "Room 4", None))

    def test_throttling_details_are_read(self):
        self.assertEqual(monitors.parse_therm("CPU_Scheduler_Limit = 100\n\tCPU_Speed_Limit \t= 62\n"), 62)
        self.assertIsNone(monitors.parse_therm("Note: No thermal warning level has been recorded"))
        self.assertEqual(monitors.parse_busiest(" 181.5 Google Chrome Helper\n  3.0 Finder\n"),
                         ("Google Chrome Helper", 181.5))
        self.assertIsNone(monitors.parse_busiest(""))

    def test_media_keys_are_decoded_and_stepped(self):
        self.assertEqual(hud_keys.decode((hud_keys.SOUND_UP << 16) | 0xA00), (hud_keys.SOUND_UP, True))
        self.assertEqual(hud_keys.decode((hud_keys.MUTE << 16) | 0xB00), (hud_keys.MUTE, False))
        self.assertEqual(hud_keys.stepped(0.375, 1), 0.4375)
        self.assertEqual(hud_keys.stepped(0.40, 1), 0.4375)          # off the marks: lands on the next one
        self.assertEqual(hud_keys.stepped(0.03, -1), 0.0)
        self.assertEqual(hud_keys.stepped(1.0, 1), 1.0)
        self.assertEqual(hud_keys.stepped(0.5, 1, fine=True), 0.515625)

    def test_battery_colours(self):
        look = monitors.battery_look
        self.assertEqual(look(55, False, True), "yellow")       # Low Power Mode wins
        self.assertEqual(look(100, True, True), "yellow")
        self.assertEqual(look(100, True, False), "green")
        self.assertEqual(look(100, False, False), "green")
        self.assertEqual(look(60, True, False), "white")        # charging, not yet full
        self.assertEqual(look(15, True, False), "white")
        self.assertEqual(look(15, False, False), "red")
        self.assertEqual(look(60, False, False), "white")

    def test_times_of_day_are_tidied(self):
        self.assertEqual([focus.clean_time(t) for t in ("9:5", "09.30", "0905", "930", " 23:59 ")],
                         ["09:05", "09:30", "09:05", "09:30", "23:59"])
        self.assertEqual([focus.clean_time(t) for t in ("", "9", "24:00", "12:60", "soon", "1:2:3")], [""] * 6)

    def test_focus_modes_start_by_time_or_app(self):
        modes = [{"name": "A", "auto_at": "09:00"}, {"name": "B", "auto_app": "Xcode"}, {"name": "C"}]
        self.assertEqual(focus.due(modes, "09:00")["name"], "A")
        self.assertEqual(focus.due(modes, "", {"xcode", "finder"})["name"], "B")
        self.assertIsNone(focus.due(modes, "09:01", {"finder", ""}))

    def test_a_banner_is_read_into_title_and_body(self):
        read = notifications.parse
        self.assertEqual(read("Messages, Sam, see you at 5", {"title": "Sam", "body": "see you at 5"}),
                         {"app": "Messages", "title": "Sam", "body": "see you at 5"})
        self.assertEqual(read("Mail, Hi, Re: plan, ok", {"title": "Hi", "subtitle": "Re: plan", "body": "ok"})["body"],
                         "Re: plan  ·  ok")
        self.assertEqual(read("Reminders", {}), {"app": "Reminders", "title": "Reminders", "body": ""})

    def test_only_new_banners_are_announced(self):
        one = {"a": {"app": "Mail", "title": "t", "body": ""}}
        self.assertEqual(notifications.fresh(one, None), [])            # the first look only takes stock
        self.assertEqual(notifications.fresh(one, set()), [one["a"]])
        self.assertEqual(notifications.fresh(one, {"a"}), [])
        own = {"b": {"app": notifications.OWN_NAME, "title": "t", "body": ""}}
        self.assertEqual(notifications.fresh(own, set()), [])
        many = {str(i): one["a"] for i in range(notifications.BURST + 1)}
        self.assertEqual(notifications.fresh(many, set()), [])          # the list was opened: not news

    def test_dragged_text_is_kept_as_a_file(self):
        with tempfile.TemporaryDirectory() as folder, Stub(shelf, "FOLDER", folder):
            values = {"shelf": [], "shelf_origins": {}}
            self.assertEqual(shelf.store_loose(values, ("text", "héllo"), now=0), (1, []))
            path = values["shelf"][0]
            self.assertTrue(os.path.basename(path).startswith("Text ") and path.endswith(".txt"))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "héllo")
            self.assertEqual(shelf.store_loose(values, ("image", b"\x89PNG"), now=0), (1, []))
            self.assertTrue(values["shelf"][1].endswith(".png"))


class MonitorTests(unittest.TestCase):
    def test_network_totals_count_each_real_interface_once(self):
        text = ("Name       Mtu   Network       Address            Ipkts Ierrs     Ibytes    Opkts Oerrs     Obytes  Coll\n"
                "lo0        16384 <Link#1>                         15671     0    4205841    15671     0    4205841     0\n"
                "en0        1500  <Link#11>   aa:bb:cc:dd:ee:ff   100     0       5000      80     0       3000     0\n"
                "en0        1500  192.168.1     192.168.1.5         100     -       5000      80     -       3000     -\n"
                "en5*       1500  <Link#7>    aa:bb:cc:dd:ee:00    10     0        700       5     0        200     0\n"
                "utun0      1380  <Link#12>                          9     0        999       9     0        999     0\n")
        self.assertEqual(monitors.parse_netstat(text), (5700, 3200))

    def test_rates_and_sizes_read_naturally(self):
        self.assertEqual(monitors.rate_text(0), "0 KB/s")
        self.assertEqual(monitors.rate_text(340_000), "340 KB/s")
        self.assertEqual(monitors.rate_text(1_250_000), "1.2 MB/s")
        self.assertEqual(monitors.size_text(2_500_000_000), "2.50 GB")

    def test_partial_downloads_are_recognised(self):
        self.assertEqual(monitors.partial_title("movie.mp4.download"), "movie.mp4")
        self.assertEqual(monitors.partial_title("setup.dmg.part"), "setup.dmg")
        self.assertEqual(monitors.partial_title("Unconfirmed 48213.crdownload"), "")
        self.assertIsNone(monitors.partial_title("notes.txt"))
        self.assertIsNone(monitors.partial_title(".download"))

    def test_downloads_are_followed_until_they_finish(self):
        with tempfile.TemporaryDirectory() as folder:
            part = os.path.join(folder, "big.zip.part")
            with open(part, "wb") as f:
                f.write(b"x" * 2000)
            with open(os.path.join(folder, "other.txt"), "w") as f:
                f.write("no")
            found = monitors.downloads_now(folder)
            self.assertEqual(list(found), [part])
            self.assertEqual(found[part][:3], ("big.zip", 2000, None))
            os.rename(part, os.path.join(folder, "big.zip"))
            self.assertEqual(monitors.finished_download(part, time.time(), folder), "big.zip")
            self.assertEqual(monitors.downloads_now(folder), {})

    def test_a_cancelled_download_is_not_announced(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(monitors.finished_download(os.path.join(folder, "a.zip.crdownload"), time.time() + 60, folder))

    def test_bluetooth_is_only_scanned_when_devices_change(self):
        mon, scans, seen = monitors.Monitors(), [], [(1,)]
        with Stub(monitors, "bluetooth", lambda: scans.append(1) or {}), \
                Stub(monitors, "bluetooth_signature", lambda: seen[0]):
            mon._bluetooth()                    # the first scan
            mon._bt_until = 0.0                 # ... and the settling time after it has passed
            mon._bluetooth()
            mon._bluetooth()
            self.assertEqual(len(scans), 1)
            seen[0] = (1, 2)                    # a device arrived
            mon._bluetooth()
            self.assertEqual(len(scans), 2)
            mon._bt_until = 0.0
            mon._bluetooth()
            self.assertEqual(len(scans), 2)
            mon._bt_next = 0.0                  # the safety net comes due
            mon._bluetooth()
            self.assertEqual(len(scans), 3)

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


class RingTests(unittest.TestCase):
    def test_positions_run_round_the_island(self):
        points = ring.positions(150, 77.5, 28, 7)
        self.assertEqual(len(points), 7)
        self.assertEqual(points[0], (-178, ring.SIDE_Y))                    # beside the island, left
        self.assertAlmostEqual(points[3][0], 0.0)                           # middle one is centred...
        self.assertAlmostEqual(points[3][1], -105.5)                        # ...and below the island
        for (x, y), (mx, my) in zip(points, reversed(points)):              # left and right mirror each other
            self.assertAlmostEqual(x, -mx)
            self.assertAlmostEqual(y, my)

    def test_buttons_do_not_overlap(self):
        inner = ring.positions(150, 77.5, 28, 8)
        outer = ring.positions(150, 77.5, 72, 9)
        points = inner + outer
        for i, (ax, ay) in enumerate(points):
            for bx, by in points[i + 1:]:
                self.assertGreater(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5, 2 * ring.RADIUS)

    def make(self, slots, items):
        """A Ring without layers: only the bookkeeping is under test."""
        r = ring.Ring.__new__(ring.Ring)
        r.slots, r.offset, r.items = slots, 0, []
        r.set_items(items)
        return r

    def test_a_few_buttons_start_in_the_middle(self):
        self.assertEqual(self.make(7, ["a", "b", "c"]).shown(), [None, None, "a", "b", "c", None, None])

    def test_a_short_ring_still_turns_and_comes_back(self):
        r = self.make(5, ["a", "b"])
        start = r.shown()
        seen = set()
        for _ in range(len(r.track())):
            r.offset = (r.offset + 1) % len(r.track())
            seen.add(tuple(r.shown()))
        self.assertEqual(r.shown(), start)                                  # a full turn ends where it began
        self.assertEqual(len(seen), 5)                                      # and passed through every position

    def test_a_long_ring_shows_a_window_and_wraps(self):
        r = self.make(3, list("abcde"))
        self.assertTrue(r.scrolls())
        self.assertEqual(r.shown(), ["a", "b", "c"])
        r.offset = 4
        self.assertEqual(r.shown(), ["e", "a", "b"])


class CategoryTests(unittest.TestCase):
    def fresh(self, **changes):
        values = {"categories": [], "known_items": [], "custom_buttons": []}
        values.update(changes)
        return values

    def test_first_run_deals_every_button_into_its_category(self):
        values = self.fresh()
        self.assertTrue(menu.normalize(values))
        placed = [item for category in values["categories"] for item in category["items"]]
        self.assertEqual(sorted(placed), sorted(menu.BUILTIN_LOOK))
        self.assertEqual(len(placed), len(set(placed)))
        self.assertEqual(menu.unused(values), [])
        self.assertFalse(menu.normalize(values))                            # and then it is stable

    def test_every_built_in_button_has_a_look(self):
        for category in menu.DEFAULT_CATEGORIES:
            for item in category["items"]:
                self.assertIn(item, menu.BUILTIN_LOOK)

    def test_custom_buttons_get_ids_and_a_home(self):
        values = self.fresh(custom_buttons=[{"name": "Mail", "kind": "url", "target": "x.com"}])
        menu.normalize(values)
        button = values["custom_buttons"][0]
        self.assertTrue(button["id"])
        mine = next(c for c in values["categories"] if c["name"] == menu.CUSTOM_CATEGORY)
        self.assertEqual(mine["items"], [menu.custom_id(button)])
        self.assertEqual(menu.describe_id(values, menu.custom_id(button)), ("star.fill", "Mail"))

    def test_a_removed_button_stays_out_but_a_new_one_comes_in(self):
        values = self.fresh()
        menu.normalize(values)
        for category in values["categories"]:
            if "dark" in category["items"]:
                category["items"].remove("dark")
        menu.normalize(values)
        self.assertEqual(menu.unused(values), ["dark"])                     # the user took it out: respected
        values["known_items"].remove("lock")                                # as if "lock" arrived in an update
        for category in values["categories"]:
            if "lock" in category["items"]:
                category["items"].remove("lock")
        menu.normalize(values)
        self.assertNotIn("lock", menu.unused(values))

    def test_deleted_and_repeated_buttons_are_cleaned_up(self):
        values = self.fresh()
        menu.normalize(values)
        values["categories"][0]["items"] += ["custom:gone", "mute", "mute"]
        menu.normalize(values)
        placed = [item for category in values["categories"] for item in category["items"]]
        self.assertNotIn("custom:gone", placed)
        self.assertEqual(placed.count("mute"), 1)

    def test_a_deleted_home_category_is_recreated_for_new_custom_buttons(self):
        values = self.fresh()
        menu.normalize(values)
        values["categories"] = [c for c in values["categories"] if c["name"] != menu.CUSTOM_CATEGORY]
        values["custom_buttons"].append({"name": "New", "kind": "url", "target": "x.com"})
        menu.normalize(values)
        self.assertIn(menu.CUSTOM_CATEGORY, [c["name"] for c in values["categories"]])


class CalendarTests(unittest.TestCase):
    def event(self, name, start, length=1800):
        return {"id": name, "title": name, "start": start, "end": start + length}

    def test_pick_next(self):
        now = 10000.0
        events = [self.event("ended", now - 7200), self.event("long ago, still on", now - 3600, 7200),
                  self.event("later", now + 7200), self.event("soon", now + 600)]
        self.assertEqual(calendar_events.pick_next(events, now)["title"], "soon")
        events.append(self.event("just started", now - 120))
        self.assertEqual(calendar_events.pick_next(events, now)["title"], "just started")
        self.assertIsNone(calendar_events.pick_next([], now))

    def test_describe(self):
        now = 10000.0
        clock = lambda t: "10:30"
        self.assertEqual(calendar_events.describe(self.event("a", now + 600), now, clock), "10:30  ·  in 10 min")
        self.assertEqual(calendar_events.describe(self.event("a", now - 60), now, clock), "10:30  ·  now")
        self.assertEqual(calendar_events.describe(self.event("a", now + 7500), now, clock), "10:30  ·  in 2 h 05 min")

    def test_nothing_is_read_without_permission(self):
        calendar = calendar_events.Calendar()
        if not calendar.authorized():
            self.assertIsNone(calendar.next_event())


class ShelfTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.root.name)
        self.home, self.other = os.path.join(base, "home"), os.path.join(base, "other")
        os.makedirs(self.home)
        os.makedirs(self.other)
        self.folder = Stub(shelf, "FOLDER", os.path.join(base, "Shelf"))
        self.folder.__enter__()
        self.values = {"shelf": [], "shelf_origins": {}}

    def tearDown(self):
        self.folder.__exit__()
        self.root.cleanup()

    def make(self, folder, name, text="x"):
        path = os.path.join(folder, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_storing_moves_the_file_and_remembers_where_it_was(self):
        path = self.make(self.home, "report.pdf", "contents")
        self.assertEqual(shelf.store(self.values, [path]), (1, []))
        self.assertFalse(os.path.exists(path))                              # it really left
        stored = self.values["shelf"][0]
        self.assertTrue(stored.startswith(shelf.FOLDER))
        self.assertEqual(os.path.basename(stored), "report.pdf")
        with open(stored) as f:
            self.assertEqual(f.read(), "contents")
        self.assertEqual(self.values["shelf_origins"][stored], self.home)

    def test_same_name_twice_does_not_clash(self):
        a = self.make(self.home, "notes.txt", "one")
        b = self.make(self.other, "notes.txt", "two")
        self.assertEqual(shelf.store(self.values, [a, b])[0], 2)
        texts = []
        for stored in self.values["shelf"]:
            with open(stored) as f:
                texts.append(f.read())
        self.assertEqual(sorted(texts), ["one", "two"])

    def test_missing_files_and_shelf_items_are_not_stored(self):
        path = self.make(self.home, "a.txt")
        shelf.store(self.values, [path])
        stored = self.values["shelf"][0]
        done, failed = shelf.store(self.values, [stored, os.path.join(self.home, "nope"), shelf.FOLDER])
        self.assertEqual(done, 0)
        self.assertEqual([name for name, _ in failed], ["nope"])
        self.assertEqual(self.values["shelf"], [stored])

    def test_folders_can_be_stored_too(self):
        folder = os.path.join(self.home, "project")
        os.makedirs(folder)
        self.make(folder, "main.py")
        self.assertEqual(shelf.store(self.values, [folder])[0], 1)
        self.assertTrue(os.path.exists(os.path.join(self.values["shelf"][0], "main.py")))

    def test_put_back_returns_it_without_overwriting(self):
        path = self.make(self.home, "report.pdf", "mine")
        shelf.store(self.values, [path])
        self.make(self.home, "report.pdf", "newer")                         # something took its old name
        back = shelf.put_back(self.values, self.values["shelf"][0])
        self.assertEqual(back, os.path.join(self.home, "report 2.pdf"))
        with open(back) as f:
            self.assertEqual(f.read(), "mine")
        with open(path) as f:
            self.assertEqual(f.read(), "newer")                             # untouched
        self.assertEqual((self.values["shelf"], self.values["shelf_origins"]), ([], {}))
        self.assertEqual(os.listdir(shelf.FOLDER), [])                      # its holder folder is gone too

    def test_put_back_all(self):
        paths = [self.make(self.home, "a.txt"), self.make(self.other, "b.txt")]
        shelf.store(self.values, paths)
        self.assertEqual(shelf.put_back_all(self.values), (2, 0))
        self.assertTrue(all(os.path.exists(p) for p in paths))
        self.assertEqual(self.values["shelf"], [])

    def test_put_back_just_one(self):
        shelf.store(self.values, [self.make(self.home, "a.txt"), self.make(self.other, "b.txt")])
        first, second = self.values["shelf"]
        self.assertEqual(shelf.put_back_all(self.values, [first]), (1, 0))
        self.assertEqual(self.values["shelf"], [second])
        self.assertTrue(os.path.exists(os.path.join(self.home, "a.txt")))

    def test_put_back_goes_somewhere_safe_when_the_old_folder_is_gone(self):
        gone = os.path.join(self.home, "temp")
        os.makedirs(gone)
        shelf.store(self.values, [self.make(gone, "a.txt")])
        os.rmdir(gone)
        desktop = os.path.join(self.home, "Desktop")
        os.makedirs(desktop)
        with Stub(shelf.os.path, "expanduser", lambda p: p.replace("~", self.home)):
            back = shelf.put_back(self.values, self.values["shelf"][0])
        self.assertEqual(back, os.path.join(desktop, "a.txt"))

    def test_an_item_dragged_out_is_forgotten(self):
        shelf.store(self.values, [self.make(self.home, "a.txt"), self.make(self.home, "b.txt")])
        first = self.values["shelf"][0]
        os.rename(first, os.path.join(self.other, "a.txt"))                 # as Finder does on a drop
        self.assertTrue(shelf.prune(self.values))
        self.assertEqual(len(self.values["shelf"]), 1)
        self.assertNotIn(first, self.values["shelf_origins"])
        self.assertFalse(shelf.prune(self.values))

    def test_old_reference_entries_are_only_forgotten(self):
        path = self.make(self.home, "kept.txt")
        self.values["shelf"].append(path)                                   # from a version that did not move files
        self.assertEqual(shelf.put_back(self.values, path), path)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.values["shelf"], [])

    def test_free_name(self):
        self.make(self.home, "a.txt")
        self.make(self.home, "a 2.txt")
        self.assertEqual(shelf._free_name(self.home, "a.txt"), os.path.join(self.home, "a 3.txt"))
        self.assertEqual(shelf._free_name(self.home, "new.txt"), os.path.join(self.home, "new.txt"))


class ButtonPictureTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.folder = Stub(custom_buttons, "PICTURES", os.path.join(os.path.realpath(self.root.name), "Icons"))
        self.folder.__enter__()
        self.icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "icon.png")

    def tearDown(self):
        self.folder.__exit__()
        self.root.cleanup()

    def test_an_image_file_becomes_a_square_png(self):
        path = custom_buttons.save_picture(self.icon)
        self.assertTrue(path.startswith(custom_buttons.PICTURES) and path.endswith(".png"))
        with open(path, "rb") as f:
            header = f.read(24)
        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
        width, height = int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
        self.assertEqual((width, height), (custom_buttons.PICTURE_SIZE, custom_buttons.PICTURE_SIZE))

    def test_an_app_gives_its_icon(self):
        self.assertIsNotNone(custom_buttons.save_picture("/System/Applications/Calculator.app"))

    def test_things_that_are_not_pictures_are_refused(self):
        self.assertIsNone(custom_buttons.save_picture("/etc/hosts"))
        self.assertIsNone(custom_buttons.save_picture("/no/such/file.png"))
        self.assertIsNone(custom_buttons.save_picture(""))

    def test_picture_of_ignores_a_picture_that_has_gone(self):
        path = custom_buttons.save_picture(self.icon)
        self.assertEqual(custom_buttons.picture_of({"image": path}), path)
        os.remove(path)
        self.assertIsNone(custom_buttons.picture_of({"image": path}))
        self.assertIsNone(custom_buttons.picture_of({"icon": "star.fill"}))

    def test_unused_pictures_are_tidied_away(self):
        used = custom_buttons.save_picture(self.icon)
        unused = custom_buttons.save_picture(self.icon)
        other = os.path.join(custom_buttons.PICTURES, "notes.txt")          # not ours: left alone
        open(other, "w").close()
        custom_buttons.tidy_pictures([{"image": used}, {"icon": "globe"}])
        self.assertTrue(os.path.exists(used))
        self.assertFalse(os.path.exists(unused))
        self.assertTrue(os.path.exists(other))

    def test_a_custom_button_carries_its_picture_into_the_ring(self):
        self.assertEqual(menu.entry("k", "star.fill", "L", lambda: "", image="/x.png").image, "/x.png")
        self.assertIsNone(menu.entry("k", "star.fill", "L", lambda: "").image)


class ShortcutTests(unittest.TestCase):
    def test_names_are_read_one_per_line_including_non_ascii(self):
        with Stub(custom_buttons.subprocess, "run", fake_run("Morning\n今天天气怎么样\n\n  Spaced  \n")):
            self.assertEqual(custom_buttons.shortcut_names(), ["Morning", "今天天气怎么样", "Spaced"])

    def test_no_tool_means_no_names(self):
        def missing(*a, **k):
            raise FileNotFoundError("shortcuts")
        with Stub(custom_buttons.subprocess, "run", missing):
            self.assertEqual(custom_buttons.shortcut_names(), [])

    def test_running_a_shortcut_passes_its_name_untouched(self):
        calls = []
        with Stub(custom_buttons.subprocess, "Popen", lambda args, **k: calls.append(args)):
            custom_buttons.run({"kind": "shortcut", "target": "嘿; rm -rf ~"})
        self.assertEqual(calls, [[custom_buttons.SHORTCUTS_TOOL, "run", "嘿; rm -rf ~"]])     # one argument, no shell

    def test_description(self):
        self.assertEqual(custom_buttons.describe({"kind": "shortcut", "target": "Morning"}),
                         "Run Shortcut  ·  Morning")


class TourTests(unittest.TestCase):
    def island(self, **state):
        """Just enough of an island for the tour's bookkeeping."""
        calls = []
        base = dict(locked=False, screen_ok=True, on_island=False, menu_open=False, menu_page="main",
                    peek_until=0.0, menu_seen=0.0, settings={"shelf": []}, calls=calls,
                    outer=SimpleNamespace(visible=False),
                    pulse=lambda color: None, refresh_tour_controls=lambda: None,
                    close_outer=lambda: None, set_page=lambda page: None)
        base.update(state)
        island = SimpleNamespace(**base)
        island.open_menu = lambda: (calls.append("open"), setattr(island, "menu_open", True))
        island.close_menu = lambda: (calls.append("close"), setattr(island, "menu_open", False))
        return island

    def run_until_moved(self, guide, now=0.0):
        """Tick until the tour leaves the stop it is on (or a second of its time passes)."""
        import tour
        start = guide.index
        for step in range(40):
            guide.tick(now + step * 0.05)
            if guide.index != start or not guide.active:
                return True
        return False

    def test_captions_are_short_enough_for_the_island(self):
        import tour
        steps = tour.Tour(self.island()).steps()
        self.assertGreaterEqual(len(steps), 8)
        for step in steps:
            self.assertLessEqual(len(step.title), 24, step.title)
            self.assertLessEqual(len(step.subtitle), 30, step.subtitle)

    def test_next_shows_only_where_nothing_has_to_be_done(self):
        import tour
        for step in tour.Tour(self.island()).steps():
            if step.done is None:
                self.assertTrue(step.next_button, step.title)
        required = [s.title for s in tour.Tour(self.island()).steps() if s.done is not None and not s.next_button]
        self.assertIn("Click the island", required)
        self.assertIn("Click a category", required)

    def test_a_stop_waits_for_the_user_and_then_moves_on(self):
        import tour
        island = self.island()
        guide = tour.Tour(island)
        guide.start()
        self.assertEqual(guide.text()[0], "Welcome")
        self.assertTrue(guide.shows_next())
        guide.advance()                                             # the user presses Next
        self.assertEqual(guide.text()[0], "Point at the island")
        self.assertFalse(guide.shows_next())                        # something has to be done here
        self.assertFalse(self.run_until_moved(guide))               # and until it is, the tour stays put
        island.on_island = True
        self.assertTrue(self.run_until_moved(guide, 10.0))
        self.assertEqual(guide.text()[0], "Click the island")

    def test_rings_are_kept_open_where_a_stop_needs_them(self):
        import tour
        island = self.island(on_island=True)
        guide = tour.Tour(island)
        guide.start()
        guide.index = 2                                             # at "Click the island"...
        island.menu_open = True                                     # ...and the user clicks it
        self.assertTrue(self.run_until_moved(guide))
        self.assertEqual(guide.text()[0], "Click a category")
        island.menu_open = False                                    # a stray click folded them
        guide.tick(100.0)
        self.assertTrue(island.menu_open)

    def test_the_drag_it_out_stop_is_left_out_if_nothing_was_added(self):
        import tour
        island = self.island()
        guide = tour.Tour(island)
        guide.start()
        titles = []
        while guide.active:
            titles.append(guide.text()[0])
            guide.advance()                                         # Next all the way through
        self.assertNotIn("Drag it out again", titles)
        self.assertEqual(titles[-1], "That's the tour")

        island = self.island()
        guide = tour.Tour(island)
        guide.start()
        while guide.text()[0] != "Drag a file onto me":
            guide.advance()
        island.settings["shelf"].append("/a/file")                  # the user drops one
        guide.advance()
        self.assertEqual(guide.text()[0], "Drag it out again")

    def test_buttons_do_nothing_real_during_the_tour(self):
        import tour
        guide = tour.Tour(self.island())
        self.assertTrue(guide.allows(SimpleNamespace(children=[1], key="category:0")))
        self.assertTrue(guide.allows(SimpleNamespace(children=None, key="settings")))
        self.assertFalse(guide.allows(SimpleNamespace(children=None, key="lock")))

    def test_it_waits_while_the_screen_is_locked(self):
        import tour
        island = self.island(locked=True)
        guide = tour.Tour(island)
        guide.start()
        self.assertTrue(guide.pending)
        self.assertFalse(guide.active)
        island.locked = False
        guide.tick(0.0)
        self.assertTrue(guide.active)
        self.assertFalse(guide.pending)


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
