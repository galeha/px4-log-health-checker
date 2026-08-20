import unittest

import numpy as np

from px4_health.candidate_v2 import _attitude, _intervals, _vibration


class Dataset:
    def __init__(self, name, data, multi_id=0):
        self.name = name
        self.multi_id = multi_id
        self.data = {key: np.asarray(value) for key, value in data.items()}


class FakeLog:
    def __init__(self, datasets, end=10_000_000):
        self.data_list = datasets
        self.start_timestamp = 0
        self.last_timestamp = end
        self.initial_parameters = {}


def vibration_log(sample_rate, amplitude=6.0, duration=8.0):
    count = int(sample_rate * duration)
    seconds = np.arange(count) / sample_rate
    timestamps = np.rint(seconds * 1e6).astype(np.int64)
    signal = amplitude * np.sin(2 * np.pi * 40.0 * seconds)
    return FakeLog([Dataset("sensor_combined", {
        "timestamp": timestamps,
        "accelerometer_m_s2[0]": signal,
        "accelerometer_m_s2[1]": np.zeros(count),
        "accelerometer_m_s2[2]": np.zeros(count),
    })], int(duration * 1e6))


def attitude_log(errors_deg, sample_rate=100):
    errors_deg = np.asarray(errors_deg, dtype=float)
    timestamps = np.rint(np.arange(len(errors_deg)) / sample_rate * 1e6).astype(np.int64)
    half = np.radians(errors_deg) / 2.0
    actual = {
        "q[0]": np.cos(half), "q[1]": np.sin(half),
        "q[2]": np.zeros(len(half)), "q[3]": np.zeros(len(half)),
    }
    desired = {
        "q_d[0]": np.ones(len(half)), "q_d[1]": np.zeros(len(half)),
        "q_d[2]": np.zeros(len(half)), "q_d[3]": np.zeros(len(half)),
    }
    end = int((len(errors_deg) - 1) / sample_rate * 1e6)
    return FakeLog([
        Dataset("vehicle_attitude", {"timestamp": timestamps, **actual}),
        Dataset("vehicle_attitude_setpoint", {"timestamp": timestamps, **desired}),
    ], end), end


class CandidateV2Tests(unittest.TestCase):
    def test_vibration_band_rms_is_similar_across_sample_rates(self):
        low = _vibration(vibration_log(100), 0, 8_000_000)
        high = _vibration(vibration_log(250), 0, 8_000_000)
        low_value = low["evidence"][0]["value"]
        high_value = high["evidence"][0]["value"]
        self.assertEqual(low["status"], "warning")
        self.assertEqual(high["status"], "warning")
        self.assertAlmostEqual(low_value, high_value, delta=0.15)

    def test_low_sample_rate_is_unavailable(self):
        result = _vibration(vibration_log(40, duration=5), 0, 5_000_000)
        self.assertEqual(result["status"], "unavailable")

    def test_single_attitude_spike_does_not_trigger_severe(self):
        errors = np.zeros(1000)
        errors[500] = 40.0
        log, end = attitude_log(errors)
        result = _attitude(log, 0, end)
        self.assertEqual(result["status"], "normal")
        self.assertEqual(result["evidence"][3]["value"], 0.01)

    def test_sustained_attitude_error_is_severe(self):
        errors = np.zeros(1000)
        errors[300:500] = 15.0
        log, end = attitude_log(errors)
        result = _attitude(log, 0, end)
        self.assertEqual(result["status"], "severe")
        self.assertGreaterEqual(result["evidence"][2]["value"], 19.0)

    def test_timestamp_gap_splits_anomaly_windows(self):
        timestamps = np.asarray([0, 100_000, 200_000, 2_000_000, 2_100_000])
        windows = _intervals(timestamps, np.ones(5, dtype=bool), 0, "异常")
        self.assertEqual(len(windows), 2)


if __name__ == "__main__":
    unittest.main()
