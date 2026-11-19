"""Growth-seed reads and selection wiring, using synthetic saves only."""
from contextlib import ExitStack
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import editor
import fefw_core as core
import fefw_layer as layer
import fefw_save as container


CAI = core.id_hash("PID_カイ")
OLYMPIA = core.id_hash("PID_オリンピア")
CATANIA = core.id_hash("PID_カターニャ")


def fixture(rows=((CAI, 0x1234ABCD, 36),)):
    """A minimal UnitPool, with independent random_seed and lottery_seed words."""
    p = bytearray(12)
    p[8:12] = b"\0\4" + struct.pack("<H", len(rows))

    def leaf(body):
        at = len(p)
        p.extend(bytes(4) + body)
        p.extend(bytes(-len(p) % 4))
        struct.pack_into("<I", p, at, len(p) + 32)

    for number, (person, seed, version) in enumerate(rows, 1):
        at = len(p)
        p.extend(bytes(72))
        p[at + 4] = version
        struct.pack_into("<IIII", p, at + 10, person, 0xF55F5AF3,
                         seed, 0x12345678)
        p[at + 59] = 8
        struct.pack_into("<H", p, at + 60, 725)
        struct.pack_into("<H", p, at + 64, 31)
        leaf(b"\0\0")  # Empty mastery and class lists.
        p.extend(b"\xff\xff\xff\xff\0\0\0\0")
        for _ in range(7):
            leaf(b"\0\0\0")  # Empty inventory and six skill lists.
        p.extend(bytes([35, 0, 0, 0, number, 0, 3, 0, 0, 0, 0, 0, 0,
                        33, 0, 0, 4, 0, 5, 0]))
        p.extend(b"\0\0\0\0\0\xff\xff\0")
        p.extend(bytes(-len(p) % 4))
        struct.pack_into("<I", p, at, len(p) + 32)
    p.extend(b"\xff\0\0\0")
    struct.pack_into("<I", p, 4, len(p) + 32)
    table = len(p)
    p.extend(struct.pack("<II", core.fnv1_32(b"UnitPool"), 4 + 32))
    struct.pack_into("<I", p, 0, (1 << 24) | (table + 32))
    return core.SaveFile(p)


def write_slot(path, rows):
    box = container.SaveFile.__new__(container.SaveFile)
    box.raw = bytearray(0x124)
    struct.pack_into("<I", box.raw, 0, container.MAGIC)
    box.zstd_offset = 0x124
    box.payload = fixture(rows).payload
    path.write_bytes(box.to_bytes())
    return layer.SaveFile(str(path))


class GrowthSeedReadTest(unittest.TestCase):
    def test_unsigned_seed_is_read_from_record_start_without_mutation(self):
        f = fixture(((CAI, 0x1234ABCD, 36), (OLYMPIA, 0, 36),
                     (CATANIA, 0xFFFFFFFF, 36)))
        first = f.units()[0]
        self.assertEqual(f.payload[first.start + 0x12:first.start + 0x1A],
                         bytes.fromhex("CD AB 34 12 78 56 34 12"))
        # Only the one-byte format marker matters, even with adjacent noise.
        f.payload[first.start + 5:first.start + 8] = b"\x7f\xfe\xff"
        before = bytes(f.payload)
        records = layer.find_units(f.payload)
        self.assertEqual([r.growth_seed for r in records],
                         [0x1234ABCD, 0, 0xFFFFFFFF])
        self.assertEqual(records[0].base, first.start + 10)
        self.assertEqual(bytes(f.payload), before)

    def test_unknown_formats_keep_existing_fields_and_have_no_seed(self):
        for version in (0, 35, 37, 255):
            with self.subTest(version=version):
                f = fixture(((CAI, 0x1234ABCD, version),))
                u = f.units()[0]
                with patch.object(f, "u32", wraps=f.u32) as read:
                    rec = layer._record(f, u)
                read.assert_not_called()
                self.assertIsNone(rec.growth_seed)
                self.assertEqual((rec.level, rec.exp, rec.max_hp), (8, 25, 31))
        self.assertIsNone(layer.UnitRecord().growth_seed)

    def test_invalid_record_bounds_never_read_seed_or_format_out_of_range(self):
        # Existing level/EXP/HP reads are deliberately separate from malformed
        # record metadata, so this test isolates the new guarded seed read.
        p = bytearray(80)
        p[0], p[4] = 8, 36
        for start, end in ((-1, 80), (0, 21), (0, 81), (61, 80),
                           (80, 80), (100, 80), (0, -1)):
            with self.subTest(start=start, end=end):
                f = SimpleNamespace(payload=p, u16=Mock(return_value=31),
                                    u32=Mock(side_effect=AssertionError("seed read")))
                u = SimpleNamespace(start=start, end=end, person=CAI, klass=0,
                                    level_off=0, exp_off=1, hp_off=3,
                                    stats=[0] * 9, classes=[], masteries=[])
                self.assertIsNone(layer._record(f, u).growth_seed)
                f.u32.assert_not_called()

    def test_seed_ending_exactly_at_record_and_payload_boundary_is_read(self):
        p = bytearray(0x16)
        p[0], p[4] = 8, 36
        struct.pack_into("<I", p, 0x12, 0x89ABCDEF)
        f = SimpleNamespace(payload=p, u16=Mock(return_value=31),
                            u32=Mock(side_effect=lambda at: struct.unpack_from("<I", p, at)[0]))
        u = SimpleNamespace(start=0, end=len(p), person=CAI, klass=0,
                            level_off=0, exp_off=1, hp_off=3,
                            stats=[0] * 9, classes=[], masteries=[])
        self.assertEqual(layer._record(f, u).growth_seed, 0x89ABCDEF)
        f.u32.assert_called_once_with(0x12)


class GrowthSeedUITest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(editor.App, "_load_settings", return_value={}))
        self.stack.enter_context(patch.object(editor.App, "_save_settings"))
        self.stack.enter_context(patch("editor.default_save_dir", return_value=None))
        # The fixture intentionally contains only UnitPool; other pages are
        # unrelated to selection, file loading, and the Stats form under test.
        for method in ("refresh_core_pages", "refresh_convoy", "refresh_supports",
                       "refresh_mounts", "_show_welcome"):
            self.stack.enter_context(patch.object(editor.App, method))
        try:
            self.app = editor.App()
        except editor.tk.TclError as exc:
            if "display" in str(exc).lower():
                self.skipTest(f"Tk display is unavailable: {exc}")
            raise
        self.addCleanup(self.app.destroy)
        self.callback_errors = Mock()
        self.app.report_callback_exception = self.callback_errors
        self.app.withdraw()
        self.app.update_idletasks()
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))

    def pick(self, uid):
        self.app.unit_tree.selection_set(str(uid))
        self.app.on_unit_select()
        self.app.update()

    def assert_seed(self, text):
        self.assertEqual(self.app.growth_seed_lbl.cget("text"), text)

    def test_selection_slots_reload_and_clear_are_read_only(self):
        a = self.app
        self.assert_seed("—")
        self.assertIsInstance(a.growth_seed_lbl, editor.ttk.Label)
        auto, route = self.folder / "Auto", self.folder / "Route_Cai_0"
        initial = ((CAI, 0x1234ABCD, 36), (OLYMPIA, 0, 36),
                   (CATANIA, 0x76543210, 35))
        for path, rows in ((auto, initial), (route, ((CAI, 0xFFFFFFFF, 36),))):
            self.assertEqual(write_slot(path, rows).verify(), [])
        original_files = {p: p.read_bytes() for p in (auto, route)}
        a.open_folder(str(self.folder), prefer=str(auto))
        original_payloads = {p: bytes(sv.payload) for p, sv in a.files.items()}
        for uid, expected in ((CAI, "0x1234ABCD"), (OLYMPIA, "0x00000000"),
                              (CATANIA, "—"), (CAI, "0x1234ABCD")):
            self.pick(uid)
            self.assert_seed(expected)
            self.assertEqual((a.lvl_var.get(), a.exp_var.get()), ("8", "25"))
        a._clear_unit_form()
        self.assert_seed("—")
        self.pick(CAI)
        a.slot_box.current(a.slot_paths.index(str(route)))
        a.on_slot_pick()
        a.update()
        self.assertEqual(a.uid, CAI)
        self.assert_seed("0xFFFFFFFF")
        a.slot_box.current(a.slot_paths.index(str(auto)))
        a.on_slot_pick()
        a.update()
        self.assert_seed("0x1234ABCD")
        self.assertEqual(a.dirty, set())
        self.assertEqual(getattr(a, "_undo_stack", []), [])
        self.assertEqual(getattr(a, "_redo_stack", []), [])
        self.assertEqual({p: bytes(sv.payload) for p, sv in a.files.items()}, original_payloads)
        self.assertEqual({p: p.read_bytes() for p in original_files}, original_files)

        # Simulate a game save, then ensure Reload reads the new current seed.
        write_slot(auto, ((CAI, 0x89ABCDEF, 36),))
        revised = auto.read_bytes()
        a.reload()
        a.update()
        self.assert_seed("0x89ABCDEF")
        self.assertEqual(a.dirty, set())
        self.assertEqual(getattr(a, "_undo_stack", []), [])
        self.assertEqual(auto.read_bytes(), revised)
        self.assertEqual(route.read_bytes(), original_files[route])
        self.callback_errors.assert_not_called()


if __name__ == "__main__":
    unittest.main()
