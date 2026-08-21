import unittest
from unittest.mock import patch

import numpy as np

from px4_health import timeline


class FakeDataset:
    def __init__(self, name, data, multi_id=0):
        self.name = name
        self.data = {key: np.asarray(value) for key, value in data.items()}
        self.multi_id = multi_id


class FakeMessage:
    def __init__(self, timestamp, level, message):
        self.timestamp = timestamp
        self._level = level
        self.message = message

    def log_level_str(self):
        return self._level


class FakeLog:
    def __init__(self, datasets=(), messages=(), embedded=True):
        self.start_timestamp = 1_000_000
        self.last_timestamp = 8_000_000
        self.data_list = list(datasets)
        self.logged_messages = list(messages)
        self.msg_info_multiple_dict = {"metadata_events": [b"test"]} if embedded else {}


class FakePX4Events:
    callback_was_offline = False

    def set_default_json_definitions_cb(self, callback):
        type(self).callback_was_offline = callback(False) is None

    def get_logged_events(self, _log):
        return [(2_000_000, "INFO", "Takeoff detected")]


class TimelineTests(unittest.TestCase):
    def test_offline_event_decode_and_duplicate_collapse(self):
        FakePX4Events.callback_was_offline = False
        event = FakeDataset("event", {"timestamp": [2_000_000], "id": [1]})
        message = FakeMessage(2_000_000, "INFO", "[commander] Takeoff detected\t")
        with patch("px4_health.timeline.PX4Events", FakePX4Events):
            result = timeline.build_timeline(FakeLog([event], [message], embedded=False))
        takeoff = next(item for item in result["items"] if item["title"] == "检测到起飞")
        self.assertTrue(FakePX4Events.callback_was_offline)
        self.assertEqual(takeoff["count"], 2)
        self.assertEqual(takeoff["source"], "event + logged_message")
        self.assertTrue(result["offline_event_decoding"])

    def test_status_failsafe_and_fault_transitions(self):
        times = [1_000_000, 2_000_000, 3_000_000]
        datasets = [
            FakeDataset("vehicle_status", {
                "timestamp": times, "arming_state": [1, 2, 1], "nav_state": [0, 0, 5], "failsafe": [0, 1, 0],
            }),
            FakeDataset("vehicle_land_detected", {"timestamp": times, "landed": [1, 0, 1]}),
            FakeDataset("failsafe_flags", {"timestamp": times, "manual_control_signal_lost": [0, 1, 0]}),
            FakeDataset("failure_detector_status", {"timestamp": times, "fd_roll": [0, 1, 0]}),
            FakeDataset("estimator_status_flags", {"timestamp": times, "cs_mag_fault": [0, 1, 0]}),
        ]
        result = timeline.build_timeline(FakeLog(datasets))
        titles = {item["title"] for item in result["items"]}
        self.assertIn("飞行器已解锁", titles)
        self.assertIn("飞行器已上锁", titles)
        self.assertIn("飞行模式切换为：自动返航", titles)
        self.assertIn("飞控进入失效保护", titles)
        self.assertIn("遥控或手动控制信号丢失", titles)
        self.assertIn("横滚姿态超限", titles)
        self.assertIn("磁力计故障", titles)
        self.assertGreaterEqual(result["summary"]["severe_count"], 2)
        self.assertGreaterEqual(result["summary"]["warning_count"], 2)

    def test_unknown_message_preserves_original(self):
        messages = [
            FakeMessage(1_500_000, "NOTICE", "[custom] Something new happened"),
            FakeMessage(1_600_000, "NOTICE", "[custom] A different unknown event"),
        ]
        result = timeline.build_timeline(FakeLog(messages=messages))
        self.assertEqual(result["items"][0]["title"], "未提供中文解释")
        self.assertEqual(result["items"][0]["original"], "[custom] Something new happened")
        self.assertEqual(len(result["items"]), 2)

    def test_common_px4_messages_use_safe_template_translations(self):
        title, translated = timeline._translate("[vehicle_imu] Accel 1 clipping, not safe to fly!")
        self.assertTrue(translated)
        self.assertEqual(title, "加速度计 1 测量超过量程，飞行不安全！")
        self.assertEqual(timeline._category("Accel 1 clipping, not safe to fly!"), "sensor")
        self.assertEqual(
            timeline._message_related_fields("Accel 1 clipping, not safe to fly!", "sensor"),
            [
                "sensor_accel[1].x", "sensor_accel[1].y", "sensor_accel[1].z",
                "sensor_accel[1].clip_counter[0]", "sensor_accel[1].clip_counter[1]",
                "sensor_accel[1].clip_counter[2]",
            ],
        )
        self.assertEqual(
            timeline._translate("primary EKF changed 1 (filter fault) -> 2"),
            ("主 EKF 因滤波器故障从实例 1 切换到实例 2", True),
        )
        self.assertEqual(
            timeline._message_related_fields("[ekf2] primary EKF changed 1 (filter fault) -> 2", "estimator"),
            [
                "estimator_selector_status[0].primary_instance",
                "estimator_status[1].filter_fault_flags",
                "estimator_status[2].filter_fault_flags",
            ],
        )
        self.assertEqual(
            timeline._translate("[logger] [logger] ./log/2026-08-14/01_55_35.ulg"),
            ("当前飞行日志文件路径已确定", True),
        )
        self.assertEqual(
            timeline._translate("[navigator] [BGarage]: Custom Landing."),
            ("执行自定义降落（第三方模块消息）", True),
        )

    def test_unknown_numeric_event_id_is_not_guessed(self):
        title, translated = timeline._translate("[Unknown event with ID 26266355]")
        self.assertFalse(translated)
        self.assertEqual(title, "无法解析的 PX4 事件（ID：26266355）")

    def test_truncation_prioritizes_important_items(self):
        messages = [FakeMessage(1_000_000 + index * 2_000_000, "INFO", f"message {index}") for index in range(6)]
        messages.append(FakeMessage(20_000_000, "ERROR", "critical failure"))
        with patch("px4_health.timeline.MAX_ITEMS", 3):
            result = timeline.build_timeline(FakeLog(messages=messages))
        self.assertTrue(result["truncated"])
        self.assertEqual(result["summary"]["total_count"], 7)
        self.assertEqual(result["summary"]["displayed_count"], 3)
        self.assertTrue(any(item["severity"] == "severe" for item in result["items"]))


if __name__ == "__main__":
    unittest.main()
