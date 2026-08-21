import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from px4_health.analyzer import AnalysisError
from px4_health.explorer import (
    LogSessionStore,
    build_catalog,
    downsample_extrema,
    field_unit,
)


class Dataset:
    def __init__(self, name, data, multi_id=0, types=None):
        self.name = name
        self.multi_id = multi_id
        self.data = {key: np.asarray(value) for key, value in data.items()}
        types = types or {}
        self.field_data = [
            SimpleNamespace(field_name=key, type_str=types.get(key, str(value.dtype)))
            for key, value in self.data.items()
        ]


class FakeLog:
    def __init__(self, datasets):
        self.data_list = datasets
        self.start_timestamp = 1_000_000
        self.last_timestamp = 11_000_000


def sample_log():
    timestamps = np.arange(1_000_000, 11_000_001, 100_000, dtype=np.int64)
    return FakeLog([
        Dataset("sensor_accel", {
            "timestamp": timestamps,
            "x": np.linspace(0, 1, len(timestamps)),
            "temperature": np.linspace(20, 25, len(timestamps)),
        }, multi_id=0),
        Dataset("sensor_accel", {
            "timestamp": timestamps,
            "x": np.linspace(1, 2, len(timestamps)),
        }, multi_id=1),
    ])


class ExplorerTests(unittest.TestCase):
    def test_catalog_keeps_instances_and_excludes_timestamp(self):
        topics, lookup = build_catalog(sample_log())
        self.assertEqual([(item["name"], item["multi_id"]) for item in topics], [
            ("sensor_accel", 0), ("sensor_accel", 1),
        ])
        self.assertIn("sensor_accel[0].x", lookup)
        self.assertIn("sensor_accel[1].x", lookup)
        self.assertFalse(any(field["name"] == "timestamp" for topic in topics for field in topic["fields"]))

    def test_extrema_downsampling_retains_spike(self):
        timestamps = np.arange(20_000)
        values = np.zeros(20_000)
        values[12_345] = 999.0
        sampled_t, sampled_v = downsample_extrema(timestamps, values, 400)
        self.assertLessEqual(len(sampled_v), 400)
        self.assertIn(999.0, sampled_v)
        self.assertEqual(sampled_t[np.argmax(sampled_v)], 12_345)

    def test_known_unit_is_conservative(self):
        self.assertEqual(field_unit("battery_status", "voltage_v"), "V")
        self.assertEqual(field_unit("sensor_accel", "x"), "m/s²")
        self.assertEqual(field_unit("sensor_accel", "y"), "m/s²")
        self.assertEqual(field_unit("sensor_accel", "z"), "m/s²")
        self.assertEqual(field_unit("sensor_accel", "temperature"), "°C")
        self.assertEqual(field_unit("sensor_accel", "clip_counter[0]"), "次")
        self.assertEqual(field_unit("sensor_accel", "clip_counter[2]"), "次")
        self.assertEqual(field_unit("custom_topic", "mystery"), "")

    def test_nav_state_catalog_includes_flight_mode_enum(self):
        timestamps = np.arange(1_000_000, 4_000_000, 1_000_000, dtype=np.int64)
        log = FakeLog([Dataset("vehicle_status", {"timestamp": timestamps, "nav_state": [17, 4, 1]})])
        topics, _ = build_catalog(log)
        field = topics[0]["fields"][0]
        modes = {item["value"]: item["label"] for item in field["enum_values"]}
        self.assertEqual(modes[17], "自动起飞")
        self.assertEqual(modes[4], "自动悬停")
        self.assertEqual(modes[1], "定高模式")

    def test_failsafe_catalog_includes_boolean_meanings(self):
        timestamps = np.arange(1_000_000, 4_000_000, 1_000_000, dtype=np.int64)
        log = FakeLog([Dataset("vehicle_status", {"timestamp": timestamps, "failsafe": [0, 1, 0]})])
        topics, _ = build_catalog(log)
        field = topics[0]["fields"][0]
        meanings = {item["value"]: item["label"] for item in field["enum_values"]}
        self.assertEqual(field["enum_title"], "数字对应的失效保护状态")
        self.assertEqual(meanings, {0: "未启用失效保护", 1: "已启用失效保护"})

    def test_filter_fault_catalog_includes_bitmask_meanings(self):
        timestamps = np.arange(1_000_000, 4_000_000, 1_000_000, dtype=np.int64)
        log = FakeLog([Dataset("estimator_status", {
            "timestamp": timestamps,
            "filter_fault_flags": [0, 1024, 3072],
        })])
        topics, _ = build_catalog(log)
        field = topics[0]["fields"][0]
        meanings = {item["value"]: item["label"] for item in field["enum_values"]}
        self.assertEqual(field["enum_title"], "EKF 内部故障位掩码")
        self.assertEqual(meanings[0], "无 EKF 内部故障")
        self.assertEqual(meanings[1024], "垂直加速度数据异常")
        self.assertEqual(meanings[2048], "加速度数据削波或非对称触顶")
        self.assertIn("3072 = 1024 + 2048", field["enum_note"])
        derived = {item["name"] for item in topics[0]["fields"] if item.get("derived")}
        self.assertIn("filter_fault_flags.bad_acc_vertical", derived)
        self.assertIn("filter_fault_flags.bad_acc_clipping", derived)

    def test_primary_estimator_instance_catalog_explains_zero_based_index(self):
        timestamps = np.arange(1_000_000, 4_000_000, 1_000_000, dtype=np.int64)
        log = FakeLog([Dataset("estimator_selector_status", {
            "timestamp": timestamps,
            "primary_instance": [1, 1, 2],
        })])
        topics, _ = build_catalog(log)
        field = topics[0]["fields"][0]
        meanings = {item["value"]: item["label"] for item in field["enum_values"]}
        self.assertEqual(field["enum_title"], "当前主 EKF 实例索引")
        self.assertEqual(meanings[0], "EKF 索引 0（第一套 EKF）")
        self.assertEqual(meanings[1], "EKF 索引 1（第二套 EKF）")
        self.assertEqual(meanings[2], "EKF 索引 2（第三套 EKF）")
        self.assertIn("索引从 0 开始", field["enum_note"])

    def test_filter_fault_derived_curves_decode_each_active_bit(self):
        timestamps = np.arange(1_000_000, 4_000_000, 1_000_000, dtype=np.int64)
        log = FakeLog([Dataset("estimator_status", {
            "timestamp": timestamps,
            "filter_fault_flags": [0, 1024, 3072],
        })])
        with tempfile.NamedTemporaryFile(suffix=".ulg", delete=False) as handle:
            path = Path(handle.name)
        store = LogSessionStore()
        try:
            with patch("px4_health.explorer.ULog", return_value=log):
                catalog = store.create(path)
            result = store.query(catalog["session_id"], [
                "estimator_status[0].filter_fault_flags.bad_acc_vertical",
                "estimator_status[0].filter_fault_flags.bad_acc_clipping",
            ], 0, 10, 200)
            values = {series["name"]: [point[1] for point in series["points"]] for series in result["series"]}
            self.assertEqual(values["filter_fault_flags.bad_acc_vertical"], [0.0, 1.0, 1.0])
            self.assertEqual(values["filter_fault_flags.bad_acc_clipping"], [0.0, 0.0, 1.0])
        finally:
            store.close()
            if path.exists():
                path.unlink()

    def test_store_queries_range_and_limits_fields(self):
        log = sample_log()
        with tempfile.NamedTemporaryFile(suffix=".ulg", delete=False) as handle:
            path = Path(handle.name)
        store = LogSessionStore()
        try:
            with patch("px4_health.explorer.ULog", return_value=log):
                catalog = store.create(path)
            result = store.query(
                catalog["session_id"], ["sensor_accel[1].x"], 2.0, 4.0, 200
            )
            self.assertEqual(len(result["series"]), 1)
            self.assertTrue(all(2.0 <= point[0] <= 4.0 for point in result["series"][0]["points"]))
            with self.assertRaises(AnalysisError):
                store.query(catalog["session_id"], ["missing[0].x"], 0, 1)
            with self.assertRaises(AnalysisError):
                store.query("expired-session", ["sensor_accel[0].x"], 0, 1)
            with self.assertRaises(AnalysisError):
                store.query(catalog["session_id"], ["sensor_accel[0].x"] * 13, 0, 1)
        finally:
            store.close()
            if path.exists():
                path.unlink()

    def test_new_session_removes_previous_temp_file(self):
        store = LogSessionStore()
        paths = []
        try:
            with patch("px4_health.explorer.ULog", return_value=sample_log()):
                for _ in range(2):
                    with tempfile.NamedTemporaryFile(suffix=".ulg", delete=False) as handle:
                        paths.append(Path(handle.name))
                    store.create(paths[-1])
            self.assertFalse(paths[0].exists())
            self.assertTrue(paths[1].exists())
        finally:
            store.close()
            for path in paths:
                if path.exists():
                    path.unlink()


if __name__ == "__main__":
    unittest.main()
