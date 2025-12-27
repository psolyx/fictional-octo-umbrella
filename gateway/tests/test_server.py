import io
import unittest

from gateway.server import greet, main


class TestGatewayServer(unittest.TestCase):
    def test_greet_defaults_to_world(self):
        self.assertEqual(greet(), "Hello, world!")

    def test_greet_strips_whitespace(self):
        self.assertEqual(greet("  Polycentric  "), "Hello, Polycentric!")

    def test_main_writes_output(self):
        buffer = io.StringIO()
        exit_code = main(["team"], output=buffer)

        self.assertEqual(exit_code, 0)
        self.assertEqual(buffer.getvalue().strip(), "Hello, team!")


if __name__ == "__main__":
    unittest.main()
