import unittest
from unittest.mock import patch

import app


class FakeTimer:
    instances = []

    def __init__(self, interval, function, args=()):
        self.interval = interval
        self.function = function
        self.args = args
        self.daemon = False
        self.instances.append(self)

    def start(self):
        pass

    def fire(self):
        self.function(*self.args)


class BrowserClientTrackerTests(unittest.TestCase):
    def setUp(self):
        FakeTimer.instances.clear()
        self.shutdown_calls = 0
        self.tracker = app.BrowserClientTracker(
            self._shutdown,
            shutdown_delay=3,
            timer_factory=FakeTimer,
        )

    def _shutdown(self):
        self.shutdown_calls += 1

    def test_last_closed_browser_schedules_shutdown(self):
        self.assertEqual(self.tracker.register("client-one"), 1)
        self.assertEqual(self.tracker.close("client-one"), 0)
        self.assertEqual(len(FakeTimer.instances), 1)

        FakeTimer.instances[0].fire()

        self.assertEqual(self.shutdown_calls, 1)

    def test_another_open_browser_keeps_server_running(self):
        self.tracker.register("client-one")
        self.tracker.register("client-two")
        self.assertEqual(self.tracker.close("client-one"), 1)
        self.assertEqual(FakeTimer.instances, [])

    def test_reload_registration_cancels_pending_shutdown(self):
        self.tracker.register("client-before-reload")
        self.tracker.close("client-before-reload")
        timer = FakeTimer.instances[0]

        self.tracker.register("client-after-reload")
        timer.fire()

        self.assertEqual(self.shutdown_calls, 0)

    def test_unknown_close_does_not_schedule_shutdown(self):
        self.assertEqual(self.tracker.close("unknown-client"), 0)
        self.assertEqual(FakeTimer.instances, [])


class ExitKeyTests(unittest.TestCase):
    def test_keypress_stops_server(self):
        class Server:
            stopped = False

            def shutdown(self):
                self.stopped = True

        server = Server()
        with patch.object(app, "_read_exit_key", return_value=True):
            app._stop_server_on_keypress(server)

        self.assertTrue(server.stopped)

    def test_missing_console_does_not_stop_server(self):
        class Server:
            stopped = False

            def shutdown(self):
                self.stopped = True

        server = Server()
        with patch.object(app, "_read_exit_key", return_value=False):
            app._stop_server_on_keypress(server)

        self.assertFalse(server.stopped)


class ConsoleOutputTests(unittest.TestCase):
    def test_chinese_output_does_not_fail_on_western_console_encoding(self):
        class Cp1252Stream:
            encoding = "cp1252"

            def __init__(self):
                self.values = []

            def write(self, value):
                value.encode(self.encoding)
                self.values.append(value)

            def flush(self):
                pass

        stream = Cp1252Stream()
        with patch("sys.stdout", stream):
            app._console_print("正在停止本地服务……")

        self.assertIn("?", "".join(stream.values))


if __name__ == "__main__":
    unittest.main()
