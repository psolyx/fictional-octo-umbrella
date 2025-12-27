import io
import unittest

from cli_app.hello import build_message, main


class TestCliHello(unittest.TestCase):
    def test_build_message_default(self):
        self.assertEqual(build_message(""), "hello from cli, world")

    def test_build_message_trims(self):
        self.assertEqual(build_message("  Alice  "), "hello from cli, Alice")

    def test_main_writes_output(self):
        buffer = io.StringIO()
        exit_code = main(["Bob"], output=buffer)

        self.assertEqual(exit_code, 0)
        self.assertEqual(buffer.getvalue().strip(), "hello from cli, Bob")


if __name__ == "__main__":
    unittest.main()
