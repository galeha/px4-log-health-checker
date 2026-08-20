from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np


PACKAGE_DIR = Path(__file__).resolve().parent
RULES = json.loads((PACKAGE_DIR / "rules_candidate_v2.json").read_text(encoding="utf-8"))
STATUS_RANK = {"unavailable": -1, "normal": 0, "warning": 1, "severe": 2}
STATUS_LABEL = {"unavailable": "数据不足", "normal": "正常", "warning": "提醒", "severe": "严重"}


def _dataset(log, name: str, multi_id: int | None = 0):
    matches = [item for item in log.data_list if item.name == name]
    if not matches:
        return None
    if multi_id is not None:
        exact = [item for item in matches if item.multi_id == multi_id]
        if exact:
            return exact[0]
    return max(matches, key=lambda item: len(item.data.get("timestamp", [])))


def _field(dataset, name: str):
    if dataset is None or name not in dataset.data:
        return None
    return np.asarray(dataset.data[name])


def _masked(dataset, field: str, start: int, end: int) -> tuple[np.ndarray, np.ndarray]:
    timestamps, values = _field(dataset, "timestamp"), _field(dataset, field)
    if timestamps is None or values is None or len(timestamps) != len(values):
        return np.asarray([], dtype=np.int64), np.asarray([], dtype=float)
    timestamps = np.asarray(timestamps, dtype=np.int64)
    mask = (timestamps >= start) & (timestamps <= end)
    return timestamps[mask], np.asarray(values)[mask]


def _sample_rate(timestamps: np.ndarray) -> float:
    if len(timestamps) < 3:
        return math.nan
    delta = np.diff(np.asarray(timestamps, dtype=np.int64)) / 1e6
    delta = delta[(delta > 0) & np.isfinite(delta)]
    if not len(delta):
        return math.nan
    median = float(np.median(delta))
    return 1.0 / median if median > 0 else math.nan


def _coverage(timestamps: np.ndarray, start: int, end: int) -> float:
    if len(timestamps) < 2 or end <= start:
        return 0.0
    observed = max(0, min(end, int(timestamps[-1])) - max(start, int(timestamps[0])))
    return min(100.0, 100.0 * observed / (end - start))


def _rate_value(timestamps: np.ndarray) -> float | None:
    value = _sample_rate(timestamps)
    return round(value, 1) if math.isfinite(value) else None


def _rank_status(rank: int) -> str:
    return ("normal", "warning", "severe")[max(0, min(2, rank))]


def _result(
    status: str,
    hits: list[str],
    quality: dict[str, Any],
    windows: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": status,
        "label": STATUS_LABEL[status],
        "algorithm_version": RULES["version"],
        "experimental": True,
        "rule_hits": hits,
        "data_quality": quality,
        "anomaly_windows": windows[:20],
        "evidence": evidence,
    }


def _unavailable(reason: str, quality: dict[str, Any] | None = None) -> dict[str, Any]:
    data_quality = quality or {}
    data_quality.setdefault("notes", []).append(reason)
    return _result("unavailable", [], data_quality, [], [])


def _intervals(
    timestamps: np.ndarray,
    active: np.ndarray,
    origin: int,
    label: str,
    severity: str = "warning",
) -> list[dict[str, Any]]:
    timestamps = np.asarray(timestamps, dtype=np.int64)
    active = np.asarray(active, dtype=bool)
    if not len(timestamps) or not np.any(active):
        return []
    median_dt = np.median(np.diff(timestamps)) if len(timestamps) > 1 else 100_000
    max_gap = max(200_000, int(3 * median_dt))
    result = []
    start_index = None
    previous_index = None
    for index in np.flatnonzero(active):
        if start_index is None or previous_index is None or timestamps[index] - timestamps[previous_index] > max_gap:
            if start_index is not None:
                result.append((start_index, previous_index))
            start_index = int(index)
        previous_index = int(index)
    if start_index is not None and previous_index is not None:
        result.append((start_index, previous_index))
    return [
        {
            "start_s": round((int(timestamps[first]) - origin) / 1e6, 3),
            "end_s": round((int(timestamps[last]) - origin) / 1e6, 3),
            "duration_s": round(max(median_dt, timestamps[last] - timestamps[first]) / 1e6, 3),
            "label": label,
            "severity": severity,
        }
        for first, last in result
    ]


def _longest(windows: list[dict[str, Any]]) -> float:
    return max((float(item["duration_s"]) for item in windows), default=0.0)


def _full_window(timestamps: np.ndarray, origin: int, label: str, severity: str) -> list[dict[str, Any]]:
    if not len(timestamps):
        return []
    start_s = max(0.0, (int(timestamps[0]) - origin) / 1e6)
    end_s = max(start_s, (int(timestamps[-1]) - origin) / 1e6)
    return [{
        "start_s": round(start_s, 3),
        "end_s": round(end_s, 3),
        "duration_s": round(end_s - start_s, 3),
        "label": label,
        "severity": severity,
    }]


def _quaternion(dataset, prefix: str) -> np.ndarray | None:
    fields = [_field(dataset, f"{prefix}[{index}]") for index in range(4)]
    if any(item is None for item in fields):
        return None
    values = np.column_stack(fields).astype(float)
    norm = np.linalg.norm(values, axis=1)
    valid = norm > 1e-9
    values[valid] /= norm[valid, None]
    values[~valid] = np.nan
    return values


def _vibration(log, start: int, end: int) -> dict[str, Any]:
    rules = RULES["vibration"]
    dataset = _dataset(log, "sensor_combined")
    timestamps = _field(dataset, "timestamp")
    axes = [_field(dataset, f"accelerometer_m_s2[{index}]") for index in range(3)]
    if timestamps is None or any(axis is None for axis in axes):
        return _unavailable("缺少 sensor_combined.accelerometer_m_s2[0..2]。")
    timestamps = np.asarray(timestamps, dtype=np.int64)
    values = np.column_stack(axes).astype(float)
    mask = (timestamps >= start) & (timestamps <= end) & np.all(np.isfinite(values), axis=1)
    timestamps, values = timestamps[mask], values[mask]
    rate = _sample_rate(timestamps)
    quality = {
        "coverage_percent": round(_coverage(timestamps, start, end), 1),
        "sample_rate_hz": _rate_value(timestamps),
        "source": "sensor_combined.accelerometer_m_s2[0..2]",
        "notes": [],
    }
    if not math.isfinite(rate) or rate < rules["minimum_sample_rate_hz"]:
        return _unavailable("采样率不足，不能可靠计算 20 Hz 以上振动频带。", quality)
    duration = rules["window_s"]
    step = duration * (1.0 - rules["overlap"])
    low_hz = rules["band_low_hz"]
    high_hz = min(rules["band_high_hz"], 0.45 * rate)
    if high_hz <= low_hz or (timestamps[-1] - timestamps[0]) / 1e6 < duration:
        return _unavailable("有效数据时长不足，不能完成频带分析。", quality)

    centers, rms_windows = [], []
    cursor = timestamps[0] / 1e6
    final = timestamps[-1] / 1e6
    sample_count = max(64, int(round(duration * rate)))
    relative_source = timestamps / 1e6
    window = np.hanning(sample_count)
    frequencies = np.fft.rfftfreq(sample_count, d=1.0 / rate)
    band = (frequencies >= low_hz) & (frequencies <= high_hz)
    weights = np.ones(len(frequencies))
    if len(weights) > 2:
        weights[1:-1] = 2.0
    while cursor + duration <= final + 1e-9:
        grid = cursor + np.arange(sample_count) / rate
        chunk = np.column_stack([np.interp(grid, relative_source, values[:, axis]) for axis in range(3)])
        chunk -= np.mean(chunk, axis=0)
        spectrum = np.fft.rfft(chunk * window[:, None], axis=0)
        power = np.abs(spectrum) ** 2
        mean_square = np.sum(power[band] * weights[band, None], axis=0) / (sample_count * np.sum(window ** 2))
        rms_windows.append(np.sqrt(np.maximum(0.0, mean_square)))
        centers.append(int((cursor + duration / 2.0) * 1e6))
        cursor += step
    centers_array = np.asarray(centers, dtype=np.int64)
    rms = np.asarray(rms_windows)
    p95 = np.percentile(rms, 95, axis=0)
    worst = np.max(rms, axis=1)
    rank = 2 if np.max(p95) >= rules["rms_severe_m_s2"] else 1 if np.max(p95) >= rules["rms_warning_m_s2"] else 0
    hits = []
    if rank:
        axis = "XYZ"[int(np.argmax(p95))]
        threshold = rules["rms_severe_m_s2"] if rank == 2 else rules["rms_warning_m_s2"]
        hits.append(f"{axis} 轴频带 RMS P95 达到 {p95.max():.2f} m/s²（阈值 {threshold:g} m/s²）")
    windows = _intervals(centers_array, worst >= rules["rms_warning_m_s2"], log.start_timestamp, "高频振动持续超限")
    return _result(
        _rank_status(rank), hits, quality, windows,
        [{"key": f"band_rms_p95_{axis.lower()}", "label": f"{axis} 轴 20–{high_hz:.0f} Hz RMS P95", "value": round(float(p95[index]), 4), "unit": "m/s²"} for index, axis in enumerate("XYZ")],
    )


def _attitude(log, start: int, end: int) -> dict[str, Any]:
    rules = RULES["attitude"]
    actual, desired = _dataset(log, "vehicle_attitude"), _dataset(log, "vehicle_attitude_setpoint")
    actual_t, desired_t = _field(actual, "timestamp"), _field(desired, "timestamp")
    actual_q, desired_q = _quaternion(actual, "q"), _quaternion(desired, "q_d")
    if actual_t is None or desired_t is None or actual_q is None or desired_q is None:
        return _unavailable("缺少实际或目标姿态四元数。")
    actual_t, desired_t = np.asarray(actual_t, dtype=np.int64), np.asarray(desired_t, dtype=np.int64)
    mask = (actual_t >= start) & (actual_t <= end) & np.all(np.isfinite(actual_q), axis=1)
    actual_t, actual_q = actual_t[mask], actual_q[mask]
    desired_valid = np.all(np.isfinite(desired_q), axis=1)
    desired_t, desired_q = desired_t[desired_valid], desired_q[desired_valid]
    quality = {
        "coverage_percent": round(_coverage(actual_t, start, end), 1),
        "sample_rate_hz": _rate_value(actual_t),
        "source": "vehicle_attitude.q / vehicle_attitude_setpoint.q_d",
        "notes": [],
    }
    if len(actual_t) < 5 or len(desired_t) < 2:
        return _unavailable("飞行阶段姿态样本不足。", quality)
    desired_q = desired_q.copy()
    for index in range(1, len(desired_q)):
        if np.dot(desired_q[index - 1], desired_q[index]) < 0:
            desired_q[index] *= -1
    interpolated = np.column_stack([np.interp(actual_t, desired_t, desired_q[:, axis]) for axis in range(4)])
    interpolated /= np.maximum(np.linalg.norm(interpolated, axis=1)[:, None], 1e-9)
    dots = np.clip(np.abs(np.sum(actual_q * interpolated, axis=1)), 0, 1)
    error = np.degrees(2 * np.arccos(dots))
    p95 = float(np.percentile(error, 95))
    warning_active, severe_active = error >= rules["warning_deg"], error >= rules["severe_deg"]
    warning_fraction, severe_fraction = float(np.mean(warning_active)), float(np.mean(severe_active))
    warning_windows = _intervals(actual_t, warning_active, log.start_timestamp, "姿态误差持续超限", "warning")
    warning_only_windows = _intervals(actual_t, warning_active & ~severe_active, log.start_timestamp, "姿态误差达到提醒范围", "warning")
    severe_windows = _intervals(actual_t, severe_active, log.start_timestamp, "姿态误差严重超限", "severe")
    severe = p95 >= rules["p95_severe_deg"] or severe_fraction >= rules["fraction_severe"] or _longest(severe_windows) >= rules["continuous_severe_s"]
    warning = p95 >= rules["p95_warning_deg"] or warning_fraction >= rules["fraction_warning"] or _longest(warning_windows) >= rules["continuous_warning_s"]
    rank = 2 if severe else 1 if warning else 0
    hits = []
    if p95 >= rules["p95_severe_deg"]:
        hits.append(f"四元数姿态误差 P95 为 {p95:.2f}°，达到严重阈值")
    elif p95 >= rules["p95_warning_deg"]:
        hits.append(f"四元数姿态误差 P95 为 {p95:.2f}°，达到提醒阈值")
    if _longest(severe_windows) >= rules["continuous_severe_s"]:
        hits.append(f"严重误差最长连续 {_longest(severe_windows):.2f} s")
    elif _longest(warning_windows) >= rules["continuous_warning_s"]:
        hits.append(f"提醒误差最长连续 {_longest(warning_windows):.2f} s")
    return _result(
        _rank_status(rank), hits, quality, severe_windows + warning_only_windows,
        [
            {"key": "quaternion_error_p95_deg", "label": "四元数误差 P95", "value": round(p95, 3), "unit": "°"},
            {"key": "over_warning_fraction_percent", "label": "误差 ≥5° 时间占比", "value": round(warning_fraction * 100, 2), "unit": "%"},
            {"key": "over_severe_fraction_percent", "label": "误差 ≥10° 时间占比", "value": round(severe_fraction * 100, 2), "unit": "%"},
            {"key": "continuous_severe_s", "label": "严重误差最长连续时间", "value": round(_longest(severe_windows), 3), "unit": "s"},
        ],
    )


def _gps(log, start: int, end: int, baseline: dict[str, Any]) -> dict[str, Any]:
    rules = RULES["gps"]
    dataset = _dataset(log, "sensor_gps") or _dataset(log, "vehicle_gps_position")
    timestamps, fix = _masked(dataset, "fix_type", start, end)
    quality = {
        "coverage_percent": round(_coverage(timestamps, start, end), 1),
        "sample_rate_hz": _rate_value(timestamps),
        "source": f"{dataset.name}.fix_type" if dataset else "未记录",
        "notes": [],
    }
    if not len(fix) or quality["coverage_percent"] < rules["minimum_coverage_percent"]:
        return _unavailable("GPS 有效数据覆盖率不足。", quality)
    invalid = np.asarray(fix, dtype=float) < rules["fix_minimum"]
    windows = _intervals(timestamps, invalid, log.start_timestamp, "定位类型低于 3D")
    longest = _longest(windows)
    rank = max(0, STATUS_RANK.get(baseline.get("status", "normal"), 0))
    if longest >= rules["invalid_fix_severe_s"]:
        rank = max(rank, 2)
    elif longest >= rules["invalid_fix_warning_s"]:
        rank = max(rank, 1)
    hits = [] if rank == 0 else [baseline.get("summary", "GPS 质量达到候选规则阈值")]
    if longest >= rules["invalid_fix_warning_s"]:
        hits.append(f"低于 3D 定位最长持续 {longest:.2f} s")
    if rank and not windows:
        windows = _full_window(timestamps, log.start_timestamp, "GPS 统计异常评估窗口", _rank_status(rank))
    return _result(
        _rank_status(rank), hits, quality, windows,
        [
            {"key": "coverage_percent", "label": "GPS 数据覆盖率", "value": quality["coverage_percent"], "unit": "%"},
            {"key": "invalid_fix_longest_s", "label": "低于 3D 定位最长时间", "value": round(longest, 3), "unit": "s"},
        ],
    )


def _battery_cell_count(log, dataset, voltage: np.ndarray) -> tuple[int | None, str]:
    cell_count = _field(dataset, "cell_count")
    if cell_count is not None:
        valid = np.asarray(cell_count, dtype=float)
        valid = valid[(valid >= 2) & (valid <= 24)]
        if len(valid):
            return int(round(float(np.median(valid)))), "日志"
    charged = (log.initial_parameters or {}).get("BAT1_V_CHARGED")
    if charged and float(charged) > 2:
        inferred = int(round(float(np.percentile(voltage, 95)) / float(charged)))
        if 2 <= inferred <= 24:
            return inferred, "按满电电压推断"
    return None, "未知"


def _battery(log, start: int, end: int, baseline: dict[str, Any]) -> dict[str, Any]:
    rules = RULES["battery"]
    datasets = [item for item in log.data_list if item.name == "battery_status"]
    dataset = next((
        item for item in datasets
        if (values := _field(item, "voltage_v")) is not None
        and np.any(np.isfinite(values))
        and float(np.nanmedian(values)) > 1.0
    ), None)
    timestamps, voltage = _masked(dataset, "voltage_v", start, end)
    _, current = _masked(dataset, "current_a", start, end)
    quality = {
        "coverage_percent": round(_coverage(timestamps, start, end), 1),
        "sample_rate_hz": _rate_value(timestamps),
        "source": "battery_status.voltage_v / current_a",
        "notes": [],
    }
    if not len(voltage) or len(current) != len(voltage):
        return _unavailable("缺少同步的电池电压和电流数据。", quality)
    finite = np.isfinite(voltage) & np.isfinite(current) & (voltage > 0)
    timestamps, voltage, current = timestamps[finite], np.asarray(voltage, dtype=float)[finite], np.asarray(current, dtype=float)[finite]
    cell_count, source = _battery_cell_count(log, dataset, voltage)
    if cell_count is None or len(voltage) < 20:
        return _unavailable("无法可靠确定电池串数或有效样本不足。", quality)
    current_span = float(np.percentile(current, 90) - np.percentile(current, 10))
    load_sag = math.nan
    resistance = math.nan
    if current_span >= rules["minimum_current_span_a"]:
        time_axis = (timestamps - timestamps[0]) / max(1, timestamps[-1] - timestamps[0])
        design = np.column_stack([np.ones(len(current)), current, time_axis])
        coefficients, *_ = np.linalg.lstsq(design, voltage, rcond=None)
        resistance = max(0.0, -float(coefficients[1]))
        load_sag = resistance * current_span / cell_count
    rank = max(0, STATUS_RANK.get(baseline.get("status", "normal"), 0))
    if math.isfinite(load_sag) and load_sag >= rules["load_sag_severe_v_per_cell"]:
        rank = max(rank, 2)
    elif math.isfinite(load_sag) and load_sag >= rules["load_sag_warning_v_per_cell"]:
        rank = max(rank, 1)
    hits = [] if rank == 0 else [baseline.get("summary", "电池达到候选规则阈值")]
    if math.isfinite(load_sag) and load_sag >= rules["load_sag_warning_v_per_cell"]:
        hits.append(f"电流相关单体压降估计为 {load_sag:.3f} V")
    quality["notes"].append(f"电池串数：{cell_count}S（{source}）")
    windows = []
    if rank:
        if current_span >= rules["minimum_current_span_a"]:
            high_load = current >= np.percentile(current, 90)
            windows = _intervals(timestamps, high_load, log.start_timestamp, "高负载电池压降评估段", _rank_status(rank))
        if not windows:
            windows = _full_window(timestamps, log.start_timestamp, "整段放电趋势统计窗口", _rank_status(rank))
    return _result(
        _rank_status(rank), hits, quality, windows,
        [
            {"key": "current_span_a", "label": "电流 P90-P10", "value": round(current_span, 3), "unit": "A"},
            {"key": "dynamic_resistance_ohm", "label": "估计整包动态内阻", "value": round(resistance, 5) if math.isfinite(resistance) else None, "unit": "Ω"},
            {"key": "load_sag_v_per_cell", "label": "电流相关单体压降", "value": round(load_sag, 4) if math.isfinite(load_sag) else None, "unit": "V"},
        ],
    )


def _motors(log, start: int, end: int) -> dict[str, Any]:
    rules = RULES["motors"]
    dataset = _dataset(log, "actuator_motors")
    timestamps = _field(dataset, "timestamp")
    controls = [_field(dataset, f"control[{index}]") for index in range(16)]
    controls = [item for item in controls if item is not None]
    if timestamps is None or not controls:
        return _unavailable("缺少 actuator_motors 电机输出数据。")
    timestamps = np.asarray(timestamps, dtype=np.int64)
    matrix = np.column_stack(controls).astype(float)
    mask = (timestamps >= start) & (timestamps <= end)
    timestamps, matrix = timestamps[mask], matrix[mask]
    matrix[(matrix < 0) | ~np.isfinite(matrix)] = np.nan
    active_columns = np.any(np.isfinite(matrix), axis=0)
    matrix = matrix[:, active_columns]
    if not matrix.size:
        return _unavailable("飞行阶段没有有效电机输出。")
    valid_rows = np.any(np.isfinite(matrix), axis=1)
    timestamps, matrix = timestamps[valid_rows], matrix[valid_rows]
    if not len(timestamps):
        return _unavailable("飞行阶段没有有效电机输出。")
    maximum = np.nanmax(matrix, axis=1)
    active = maximum >= rules["saturation_level"]
    windows = _intervals(timestamps, active, log.start_timestamp, "电机输出接近饱和")
    longest = _longest(windows)
    allocator = _dataset(log, "control_allocator_status")
    allocator_t, torque_ok = _masked(allocator, "torque_setpoint_achieved", start, end)
    _, thrust_ok = _masked(allocator, "thrust_setpoint_achieved", start, end)
    allocator_failure = math.nan
    allocator_active = np.asarray([], dtype=bool)
    if len(torque_ok) and len(thrust_ok) == len(torque_ok):
        allocator_active = (np.asarray(torque_ok) == 0) | (np.asarray(thrust_ok) == 0)
        allocator_failure = float(np.mean(allocator_active))
    rank = 2 if longest >= rules["continuous_severe_s"] else 1 if longest >= rules["continuous_warning_s"] else 0
    if math.isfinite(allocator_failure):
        if allocator_failure >= rules["allocator_failure_fraction_severe"]:
            rank = max(rank, 2)
        elif allocator_failure >= rules["allocator_failure_fraction_warning"]:
            rank = max(rank, 1)
    if math.isfinite(allocator_failure) and allocator_failure >= rules["allocator_failure_fraction_warning"]:
        allocator_severity = "severe" if allocator_failure >= rules["allocator_failure_fraction_severe"] else "warning"
        windows.extend(_intervals(allocator_t, allocator_active, log.start_timestamp, "控制分配未实现", allocator_severity))
    hits = []
    if longest >= rules["continuous_warning_s"]:
        hits.append(f"接近饱和最长连续 {longest:.2f} s")
    if math.isfinite(allocator_failure) and allocator_failure >= rules["allocator_failure_fraction_warning"]:
        hits.append(f"控制分配未实现占比 {allocator_failure * 100:.2f}%")
    quality = {
        "coverage_percent": round(_coverage(timestamps, start, end), 1),
        "sample_rate_hz": _rate_value(timestamps),
        "source": "actuator_motors.control[]" + (" / control_allocator_status" if allocator else ""),
        "notes": [] if allocator else ["日志未记录 control_allocator_status，未检查控制分配饱和。"],
    }
    return _result(
        _rank_status(rank), hits, quality, windows,
        [
            {"key": "near_saturation_longest_s", "label": "接近饱和最长连续时间", "value": round(longest, 3), "unit": "s"},
            {"key": "near_saturation_fraction_percent", "label": "接近饱和时间占比", "value": round(float(np.mean(active)) * 100, 3), "unit": "%"},
            {"key": "allocator_failure_fraction_percent", "label": "控制分配未实现占比", "value": round(allocator_failure * 100, 3) if math.isfinite(allocator_failure) else None, "unit": "%"},
        ],
    )


def analyze_candidate_v2(log, start: int, end: int, baseline_metrics: list[dict[str, Any]], has_flight: bool) -> dict[str, dict[str, Any]]:
    baseline = {item["id"]: item for item in baseline_metrics}
    if not has_flight:
        return {metric_id: _unavailable("未检测到有效飞行阶段。") for metric_id in baseline}
    analyzers = {
        "vibration": lambda: _vibration(log, start, end),
        "gps": lambda: _gps(log, start, end, baseline["gps"]),
        "battery": lambda: _battery(log, start, end, baseline["battery"]),
        "attitude": lambda: _attitude(log, start, end),
        "motors": lambda: _motors(log, start, end),
    }
    result = {}
    for metric_id, function in analyzers.items():
        try:
            result[metric_id] = function()
        except Exception as exc:
            result[metric_id] = _unavailable(f"候选算法计算失败：{exc}")
    return result
