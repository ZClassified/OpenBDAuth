import unittest
import os
from modules.mux_engine import find_tsmuxer

class TestMuxEngine(unittest.TestCase):
    def test_find_tsmuxer(self):
        # tsMuxeR sollte nun im Projektverzeichnis 'tools/' oder im System gefunden werden
        path = find_tsmuxer()
        self.assertIsNotNone(path, "find_tsmuxer() should locate tsMuxeR.exe in tools/ or PATH")
        self.assertTrue(os.path.exists(path), f"Path {path} does not exist")
