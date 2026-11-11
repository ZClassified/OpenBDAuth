# tests/test_bdsim_scratch.py
"""Simulator: Hilfsregister (vor jedem Lesen ohne Bedingung beschrieben) unterscheiden keine Zustände (v1.13.0)."""

import unittest

from modules.bdmv.movie_object_generator import (
    start_page_commands, menu_loop_commands, cmd_move_gpr, cmd_compare_gpr, cmd_copy_gpr, CMP_EQ,
    GPR_PAGE_NOW, GPR_BUTTON_NOW,
)
from modules.bdsim.hdmv import decode_command, scratch_registers


def parse(raws):
    return [decode_command(r) for r in raws]


class TestScratchRegisters(unittest.TestCase):
    def test_start_page_scratch(self):
        lists = [parse(start_page_commands(1)), parse(menu_loop_commands(0, 0, True, 1))]
        self.assertEqual(scratch_registers(lists), frozenset({GPR_PAGE_NOW, GPR_BUTTON_NOW}))

    def test_read_before_write_is_live(self):
        lists = [parse([cmd_copy_gpr(20, 21), cmd_move_gpr(21, 5)])]
        self.assertNotIn(21, scratch_registers(lists))          # erst gelesen, dann geschrieben: zählt
        self.assertIn(20, scratch_registers(lists))             # nie gelesen: spielt keine Rolle

    def test_conditional_write_does_not_count(self):
        lists = [parse([cmd_compare_gpr(CMP_EQ, 1, 0), cmd_move_gpr(30, 1), cmd_copy_gpr(31, 30)])]
        self.assertNotIn(30, scratch_registers(lists))
        self.assertIn(31, scratch_registers(lists))


if __name__ == "__main__":
    unittest.main()
