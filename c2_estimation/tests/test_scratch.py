"""Organization checks with new disposable fixtures, never existing study data."""
from pathlib import Path
import unittest
from c2_estimation.tests.scratch import temporary_directory


class ScratchTests(unittest.TestCase):
    def test_scoped_directory_is_removed_after_use(self):
        with temporary_directory(prefix="layout-test-") as name:
            path = Path(name)
            self.assertEqual(path.parent.parts[-3:], ("c2_v4", "_scratch", "tests"))
            (path / "fixture.txt").write_text("synthetic fixture", encoding="utf-8")
        self.assertFalse(path.exists())

    def test_prefix_cannot_escape_the_fixture_directory(self):
        for prefix in ("../outside", "x/y", "x\\y", "D:elsewhere", ""):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                temporary_directory(prefix=prefix)
