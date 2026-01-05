import json
import tempfile
import unittest
from pathlib import Path

from cli_app.tui_model import TuiModel, load_settings


class TuiModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpfile = tempfile.NamedTemporaryFile(delete=False)
        self.addCleanup(self._cleanup_file)

    def _cleanup_file(self) -> None:
        try:
            self.tmpfile.close()
        finally:
            try:
                Path(self.tmpfile.name).unlink()
            except FileNotFoundError:
                pass

    def test_focus_cycles_with_tab(self):
        model = TuiModel({}, settings_path=self.tmpfile.name)
        self.assertEqual(model.render().focus_area, "menu")

        model.handle_key("TAB")
        self.assertEqual(model.render().focus_area, "fields")

        model.handle_key("TAB")
        self.assertEqual(model.render().focus_area, "log")

        model.handle_key("SHIFT_TAB")
        self.assertEqual(model.render().focus_area, "fields")

    def test_menu_selection_and_activation(self):
        model = TuiModel({}, settings_path=self.tmpfile.name)
        model.handle_key("DOWN")
        self.assertEqual(model.render().selected_menu, 1)
        self.assertEqual(model.current_action(), "smoke")

        action = model.handle_key("ENTER")
        self.assertEqual(action, "run")

        for _ in range(len(model.menu_items) - 2):
            model.handle_key("DOWN")
        self.assertEqual(model.current_action(), "quit")
        self.assertEqual(model.handle_key("ENTER"), "quit")

    def test_field_editing_persists(self):
        model = TuiModel({"state_dir": ""}, settings_path=self.tmpfile.name)
        model.handle_key("TAB")

        model.handle_key("CHAR", "a")
        model.handle_key("CHAR", "b")
        with open(self.tmpfile.name, encoding="utf-8") as handle:
            persisted = json.loads(handle.read())
        self.assertEqual(persisted["state_dir"], "ab")

        model.handle_key("BACKSPACE")
        persisted = load_settings(self.tmpfile.name)
        self.assertEqual(persisted["state_dir"], "a")

    def test_log_scroll_moves_selection(self):
        model = TuiModel({}, settings_path=self.tmpfile.name)
        model.append_log([f"line {i}" for i in range(10)])
        model.handle_key("TAB")
        model.handle_key("TAB")
        self.assertEqual(model.render().focus_area, "log")
        self.assertEqual(model.render().log_scroll, 0)

        model.handle_key("UP")
        self.assertEqual(model.render().log_scroll, 1)
        model.handle_key("DOWN")
        self.assertEqual(model.render().log_scroll, 0)


if __name__ == "__main__":
    unittest.main()
