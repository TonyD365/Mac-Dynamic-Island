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
    def test_captions_are_short_enough_for_the_island(self):
        import tour
        steps = tour.Tour(SimpleNamespace(pulse=None, open_menu=None)).steps()
        self.assertGreaterEqual(len(steps), 5)
        for title, subtitle, _ in steps:
            self.assertLessEqual(len(title), 24, title)
            self.assertLessEqual(len(subtitle), 30, subtitle)

    def test_it_waits_while_the_screen_is_locked(self):
        import tour
        island = SimpleNamespace(locked=True, screen_ok=True)
        guide = tour.Tour(island)
        guide.start()
        self.assertTrue(guide.pending)
        self.assertFalse(guide.active)
        island.locked = False
        guide.start()
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
