import unittest

import numpy as np

from px4_health.analyzer import (
    _attitude,
    _battery,
    _flight_window,
    _gps,
    _motors,
    _vibration,
)


class Dataset:
    def __init__(self, name, data, multi_id=0):
        self.name = name
        self.data = {key: np.asarray(value) for key, value in data.items()}
        self.multi_id = multi_id


class FakeLog:
    def __init__(self, datasets, parameters=None):
        self.data_list = datasets
        self.initial_parameters = parameters or {}
        self.changed_parameters = []
        self.start_timestamp = 0
        self.last_timestamp = 10_000_000


def timestamps(count=100):
    return np.linspace(1_000_000, 9_000_000, count, dtype=np.int64)


class AnalysisRuleTests(unittest.TestCase):
    def test_gps_bad_fix_is_severe(self):
        t = timestamps()
        log = FakeLog([Dataset("sensor_gps", {
            "timestamp": t,
            "fix_type": np.full(len(t), 2),
            "satellites_used": np.full(len(t), 5),
            "eph": np.full(len(t), 6.0),
            "epv": np.full(len(t), 9.0),
            "jamming_state": np.zeros(len(t)),
            "spoofing_state": np.ones(len(t)),
        })])
        self.assertEqual(_gps(log, 0, 10_000_000)["status"], "severe")

    def test_pack_voltage_can_infer_cell_count(self):
        t = timestamps()
        voltage = np.linspace(55.0, 53.5, len(t))
        log = FakeLog([Dataset("battery_status", {
            "timestamp": t,
            "voltage_v": voltage,
            "current_a": np.linspace(10, 30, len(t)),
            "cell_count": np.ones(len(t)),
            "warning": np.zeros(len(t)),
            "max_cell_voltage_delta": np.zeros(len(t)),
        })], {"BAT1_V_CHARGED": 4.05})
        result = _battery(log, 0, 10_000_000)
        self.assertEqual(result["status"], "normal")
        self.assertTrue(any("推断" in item["label"] for item in result["evidence"]))

    def test_identical_quaternions_track_well(self):
        t = timestamps()
        quaternion = {
            "q[0]": np.ones(len(t)), "q[1]": np.zeros(len(t)),
            "q[2]": np.zeros(len(t)), "q[3]": np.zeros(len(t)),
        }
        desired = {key.replace("q[", "q_d["): value for key, value in quaternion.items()}
        log = FakeLog([
            Dataset("vehicle_attitude", {"timestamp": t, **quaternion}),
            Dataset("vehicle_attitude_setpoint", {"timestamp": t, **desired}),
        ])
        self.assertEqual(_attitude(log, 0, 10_000_000)["status"], "normal")

    def test_sustained_motor_saturation_is_severe(self):
        t = timestamps()
        log = FakeLog([Dataset("actuator_motors", {
            "timestamp": t,
            "control[0]": np.full(len(t), 0.98),
            "control[1]": np.full(len(t), 0.96),
            "control[2]": np.full(len(t), 0.97),
            "control[3]": np.full(len(t), 0.99),
        })])
        self.assertEqual(_motors(log, 0, 10_000_000)["status"], "severe")

    def test_accelerometer_clipping_is_severe(self):
        t = timestamps(2)
        log = FakeLog([Dataset("sensor_accel", {
            "timestamp": t,
            "clip_counter[0]": [0, 100],
            "clip_counter[1]": [0, 0],
            "clip_counter[2]": [0, 0],
        })])
        self.assertEqual(_vibration(log, 0, 10_000_000)["status"], "severe")

    def test_vibration_rms_is_reported_per_axis(self):
        t = timestamps(100)
        x = np.tile([-10.0, 10.0], 50)
        log = FakeLog([Dataset("sensor_combined", {
            "timestamp": t,
            "accelerometer_m_s2[0]": x,
            "accelerometer_m_s2[1]": np.zeros(len(t)),
            "accelerometer_m_s2[2]": np.zeros(len(t)),
        })])
        result = _vibration(log, 0, 10_000_000)
        labels = [item["label"] for item in result["evidence"]]
        self.assertEqual(result["status"], "severe")
        self.assertIn("X 轴高频加速度 RMS", labels)
        self.assertIn("Y 轴高频加速度 RMS", labels)
        self.assertIn("Z 轴高频加速度 RMS", labels)
        self.assertEqual(result["data_sources"][0]["field"], "accelerometer_m_s2[0..2]")

    def test_landed_log_has_no_flight_window(self):
        t = timestamps(4)
        log = FakeLog([
            Dataset("vehicle_land_detected", {"timestamp": t, "landed": np.ones(len(t))}),
            Dataset("vehicle_status", {"timestamp": t, "arming_state": np.ones(len(t))}),
        ])
        *_, has_flight = _flight_window(log)
        self.assertFalse(has_flight)


if __name__ == "__main__":
    unittest.main()
