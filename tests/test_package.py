import unittest

import chimebuddy


class PackageTests(unittest.TestCase):
    def test_version_is_defined(self) -> None:
        self.assertEqual(chimebuddy.__version__, "2.0.0.dev0")


if __name__ == "__main__":
    unittest.main()