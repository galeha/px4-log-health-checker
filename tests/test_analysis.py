import unittest

import numpy as np

from px4_health.analyzer import (
    _attitude,
    _battery,
    _flight_window,
    _gps,
    _magnetometer,
    _motors,
    _overall_summary,
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
    @staticmethod
    def _mag_log(magnetic_x, extra=None, parameters=None):
        t = np.linspace(500_000, 11_500_000, len(magnetic_x), dtype=np.int64)
        datasets = [Dataset("vehicle_magnetometer", {
            "timestamp": t,
            "magnetometer_ga[0]": magnetic_x,
            "magnetometer_ga[1]": np.zeros(len(t)),
            "magnetometer_ga[2]": np.zeros(len(t)),
        })]
        datasets.extend(extra or [])
        return FakeLog(datasets, parameters), t

    def test_stable_magnetic_field_is_normal_but_power_relation_can_be_unavailable(self):
        log, _ = self._mag_log(np.full(120, 0.5))
        result = _magnetometer(log, 0, 12_000_000)
        self.assertEqual(result["status"], "normal")
        self.assertEqual(result["name"], "磁力计异常（实验）")
        self.assertNotIn("动力干扰", result["name"])
        self.assertEqual(result["power_relation"], "无法判断")
        self.assertTrue(result["experimental"])
        self.assertFalse(result["affects_overall"])

    def test_magnetometer_selects_dynamic_propulsion_battery_instance(self):
        count = 120
        t = np.linspace(500_000, 11_500_000, count, dtype=np.int64)
        propulsion_current = np.linspace(0, 30, count)
        magnetic = 0.4 + propulsion_current * 0.01
        log, _ = self._mag_log(magnetic, [
            Dataset("battery_status", {"timestamp": t, "current_a": np.full(count, 0.07)}, multi_id=0),
            Dataset("battery_status", {"timestamp": t, "current_a": propulsion_current}, multi_id=1),
        ])
        result = _magnetometer(log, 0, 12_000_000)
        self.assertEqual(result["status"], "severe")
        self.assertEqual(result["power_relation"], "明显")
        evidence = {item["label"]: item["value"] for item in result["evidence"]}
        self.assertEqual(evidence["动力负载数据源"], "battery_status[1].current_a")
        source_evidence = next(item for item in result["evidence"] if item["label"] == "动力负载数据源")
        self.assertEqual(source_evidence["full_value"], "battery_status[1].current_a")

    def test_motor_output_is_low_confidence_fallback(self):
        count = 120
        t = np.linspace(500_000, 11_500_000, count, dtype=np.int64)
        motor_load = np.linspace(0, 1, count)
        log, _ = self._mag_log(0.4 + motor_load * 0.3, [Dataset("actuator_motors", {
            "timestamp": t,
            "control[0]": motor_load,
            "control[1]": motor_load,
            "control[2]": motor_load,
            "control[3]": motor_load,
        })])
        result = _magnetometer(log, 0, 12_000_000)
        self.assertEqual(result["power_relation"], "明显")
        self.assertTrue(any("低可信度" in note for note in result["data_quality"]["notes"]))

    def test_sustained_ekf_magnetic_disturbance_is_severe(self):
        count = 120
        t = np.linspace(500_000, 11_500_000, count, dtype=np.int64)
        log, _ = self._mag_log(np.full(count, 0.5), [Dataset("estimator_status_flags", {
            "timestamp": t, "cs_mag_field_disturbed": np.ones(count), "cs_mag_fault": np.zeros(count),
        })])
        result = _magnetometer(log, 0, 12_000_000)
        self.assertEqual(result["status"], "severe")
        self.assertTrue(result["anomaly_windows"])

    def test_isolated_magnetic_spike_does_not_make_result_severe(self):
        count = 120
        t = np.linspace(500_000, 11_500_000, count, dtype=np.int64)
        magnetic = np.full(count, 0.5)
        magnetic[count // 2] = 4.0
        disturbed = np.zeros(count)
        disturbed[count // 2] = 1
        log, _ = self._mag_log(magnetic, [Dataset("estimator_status_flags", {
            "timestamp": t, "cs_mag_field_disturbed": disturbed, "cs_mag_fault": np.zeros(count),
        })])
        self.assertEqual(_magnetometer(log, 0, 12_000_000)["status"], "normal")

    def test_mag_fault_is_severe(self):
        count = 120
        t = np.linspace(500_000, 11_500_000, count, dtype=np.int64)
        fault = np.zeros(count)
        fault[50] = 1
        log, _ = self._mag_log(np.full(count, 0.5), [Dataset("estimator_status_flags", {
            "timestamp": t, "cs_mag_field_disturbed": np.zeros(count), "cs_mag_fault": fault,
        })])
        self.assertEqual(_magnetometer(log, 0, 12_000_000)["status"], "severe")

    def test_disabled_mag_check_does_not_treat_disturbed_flag_as_active_rule(self):
        count = 120
        t = np.linspace(500_000, 11_500_000, count, dtype=np.int64)
        log, _ = self._mag_log(np.full(count, 0.5), [Dataset("estimator_status_flags", {
            "timestamp": t, "cs_mag_field_disturbed": np.ones(count), "cs_mag_fault": np.zeros(count),
        })], {"EKF2_MAG_CHECK": 0})
        result = _magnetometer(log, 0, 12_000_000)
        self.assertEqual(result["status"], "normal")
        self.assertTrue(any("EKF2_MAG_CHECK=0" in note for note in result["data_quality"]["notes"]))

    def test_primary_ekf_selector_ignores_backup_disturbance(self):
        count = 120
        t = np.linspace(500_000, 11_500_000, count, dtype=np.int64)
        log, _ = self._mag_log(np.full(count, 0.5), [
            Dataset("estimator_selector_status", {"timestamp": t, "primary_instance": np.ones(count)}),
            Dataset("estimator_status_flags", {
                "timestamp": t, "cs_mag_field_disturbed": np.ones(count), "cs_mag_fault": np.zeros(count),
            }, multi_id=0),
            Dataset("estimator_status_flags", {
                "timestamp": t, "cs_mag_field_disturbed": np.zeros(count), "cs_mag_fault": np.zeros(count),
            }, multi_id=1),
        ])
        self.assertEqual(_magnetometer(log, 0, 12_000_000)["status"], "normal")

    def test_missing_magnetometer_data_is_unavailable(self):
        result = _magnetometer(FakeLog([]), 0, 12_000_000)
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(result["experimental"])

    def test_experimental_magnetometer_does_not_change_overall(self):
        metrics = [
            {"id": "vibration", "status": "normal"},
            {"id": "magnetometer", "status": "severe", "affects_overall": False},
        ]
        self.assertEqual(_overall_summary(metrics), "未发现明显异常")

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
        result = _attitude(log, 0, 10_000_000)
        self.assertEqual(result["status"], "normal")
        self.assertEqual([series["name"] for series in result["series"]], ["横滚姿态", "俯仰姿态", "偏航姿态"])
        self.assertTrue(all([line["name"] for line in series["lines"]] == ["实际", "目标"] for series in result["series"]))
        evidence_labels = [item["label"] for item in result["evidence"]]
        self.assertIn("四元数综合误差 P95", evidence_labels)
        self.assertIn("横滚误差 P95", evidence_labels)
        self.assertIn("俯仰误差 P95", evidence_labels)
        self.assertIn("偏航误差 P95", evidence_labels)

    def test_sustained_motor_saturation_is_severe(self):
        t = timestamps()
        log = FakeLog([Dataset("actuator_motors", {
            "timestamp": t,
            "control[0]": np.full(len(t), 0.98),
            "control[1]": np.full(len(t), 0.96),
            "control[2]": np.full(len(t), 0.97),
            "control[3]": np.full(len(t), 0.99),
        })])
        result = _motors(log, 0, 10_000_000)
        self.assertEqual(result["status"], "severe")
        labels = [item["label"] for item in result["evidence"]]
        self.assertIn("时刻最大电机输出 P95", labels)
        self.assertIn("全程瞬时最大输出", labels)

    def test_accelerometer_clipping_is_severe(self):
        t = timestamps(2)
        log = FakeLog([Dataset("sensor_accel", {
            "timestamp": t,
            "clip_counter[0]": [0, 100],
            "clip_counter[1]": [0, 0],
            "clip_counter[2]": [0, 0],
        })])
        self.assertEqual(_vibration(log, 0, 10_000_000)["status"], "severe")

    def test_clipping_uses_all_imu_instances_and_cumulative_increments(self):
        t = timestamps(4)
        log = FakeLog([
            Dataset("vehicle_imu_status", {
                "timestamp": t,
                "accel_clipping[0]": [0, 0, 0, 0],
                "accel_clipping[1]": [0, 0, 0, 0],
                "accel_clipping[2]": [0, 4, 4, 4],
            }, multi_id=0),
            Dataset("vehicle_imu_status", {
                "timestamp": t,
                "accel_clipping[0]": [0, 0, 0, 0],
                "accel_clipping[1]": [0, 0, 0, 0],
                "accel_clipping[2]": [0, 5, 9, 9],
            }, multi_id=1),
        ])
        result = _vibration(log, 0, 10_000_000)
        evidence = {item["label"]: item["value"] for item in result["evidence"]}
        self.assertEqual(evidence["加速度计削波总次数"], "13 次")
        self.assertEqual(evidence["IMU 0 Z 轴加速度削波"], "4 次")
        self.assertEqual(evidence["IMU 1 Z 轴加速度削波"], "9 次")

    def test_sensor_accel_fallback_sums_period_counts_and_instances(self):
        t = timestamps(3)
        log = FakeLog([
            Dataset("sensor_accel", {
                "timestamp": t,
                "clip_counter[0]": [0, 0, 0],
                "clip_counter[1]": [0, 0, 0],
                "clip_counter[2]": [0, 4, 0],
            }, multi_id=0),
            Dataset("sensor_accel", {
                "timestamp": t,
                "clip_counter[0]": [0, 0, 0],
                "clip_counter[1]": [0, 0, 0],
                "clip_counter[2]": [6, 4, 0],
            }, multi_id=1),
        ])
        result = _vibration(log, 0, 10_000_000)
        evidence = {item["label"]: item["value"] for item in result["evidence"]}
        self.assertEqual(evidence["加速度计削波总次数"], "14 次")
        self.assertEqual(evidence["IMU 0 Z 轴加速度削波"], "4 次")
        self.assertEqual(evidence["IMU 1 Z 轴加速度削波"], "10 次")

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
