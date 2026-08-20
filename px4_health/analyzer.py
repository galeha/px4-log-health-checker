from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from pyulog import ULog


PACKAGE_DIR = Path(__file__).resolve().parent
RULES = json.loads((PACKAGE_DIR / "rules_v1.json").read_text(encoding="utf-8"))
GLOSSARY = json.loads((PACKAGE_DIR / "parameter_glossary.json").read_text(encoding="utf-8"))

TOPICS = [
    "actuator_motors",
    "battery_status",
    "control_allocator_status",
    "estimator_status",
    "estimator_status_flags",
    "sensor_accel",
    "sensor_combined",
    "sensor_gps",
    "vehicle_gps_position",
    "vehicle_attitude",
    "vehicle_attitude_setpoint",
    "vehicle_land_detected",
    "vehicle_status",
]


class AnalysisError(RuntimeError):
    pass


def _dataset(log: ULog, name: str, multi_id: int | None = 0):
    matches = [d for d in log.data_list if d.name == name]
    if not matches:
        return None
    if multi_id is not None:
        exact = [d for d in matches if d.multi_id == multi_id]
        if exact:
            return exact[0]
    return max(matches, key=lambda d: len(d.data.get("timestamp", [])))


def _field(dataset, *names: str) -> np.ndarray | None:
    if dataset is None:
        return None
    for name in names:
        if name in dataset.data:
            return np.asarray(dataset.data[name])
    return None


def _finite(values: np.ndarray | None) -> np.ndarray:
    if values is None:
        return np.asarray([], dtype=float)
    values = np.asarray(values, dtype=float)
    return values[np.isfinite(values)]


def _percentile(values: np.ndarray | None, q: float, default: float = math.nan) -> float:
    clean = _finite(values)
    return float(np.percentile(clean, q)) if clean.size else default


def _flight_window(log: ULog) -> tuple[int, int, str, bool]:
    landed = _dataset(log, "vehicle_land_detected")
    timestamps = _field(landed, "timestamp")
    states = _field(landed, "landed")
    if timestamps is not None and states is not None:
        airborne = np.asarray(states) == 0
        if np.any(airborne):
            times = np.asarray(timestamps, dtype=np.int64)[airborne]
            return int(times[0]), int(times[-1]), "已按起飞至着陆阶段分析", True

    status = _dataset(log, "vehicle_status")
    timestamps = _field(status, "timestamp")
    arming = _field(status, "arming_state")
    if timestamps is not None and arming is not None:
        armed = np.asarray(arming) == 2
        if np.any(armed):
            times = np.asarray(timestamps, dtype=np.int64)[armed]
            return int(times[0]), int(times[-1]), "未找到着陆标志，已按解锁阶段分析", True

    return int(log.start_timestamp), int(log.last_timestamp), "未检测到起飞或解锁飞行阶段", False


def _masked(dataset, start: int, end: int, field: str) -> tuple[np.ndarray, np.ndarray]:
    timestamps = _field(dataset, "timestamp")
    values = _field(dataset, field)
    if timestamps is None or values is None:
        return np.asarray([]), np.asarray([])
    timestamps = np.asarray(timestamps, dtype=np.int64)
    values = np.asarray(values)
    mask = (timestamps >= start) & (timestamps <= end)
    return timestamps[mask], values[mask]


def _status(rank: int) -> str:
    return ("normal", "warning", "severe")[max(0, min(2, rank))]


def _series(name: str, unit: str, timestamps: np.ndarray, values: np.ndarray, origin: int) -> dict[str, Any]:
    timestamps = np.asarray(timestamps)
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    timestamps, values = timestamps[finite], values[finite]
    if values.size > 900:
        indices = np.linspace(0, values.size - 1, 900, dtype=int)
        timestamps, values = timestamps[indices], values[indices]
    points = [[round((int(t) - origin) / 1e6, 3), round(float(v), 5)] for t, v in zip(timestamps, values)]
    return {"name": name, "unit": unit, "points": points}


def _multi_series(name: str, unit: str, timestamps: np.ndarray, lines: Iterable[tuple[str, np.ndarray]], origin: int) -> dict[str, Any]:
    return {
        "name": name,
        "unit": unit,
        "lines": [
            {"name": line_name, "points": _series(line_name, unit, timestamps, values, origin)["points"]}
            for line_name, values in lines
        ],
    }


def _evidence(label: str, value: Any, unit: str = "") -> dict[str, str]:
    if isinstance(value, float):
        text = f"{value:.3g}"
    else:
        text = str(value)
    return {"label": label, "value": f"{text}{(' ' + unit) if unit else ''}"}


def _source(topic: str, field: str, zh: str, unit: str, usage: str) -> dict[str, str]:
    return {"topic": topic, "field": field, "zh": zh, "unit": unit, "usage": usage}


def _parameters(log: ULog, group: str) -> list[dict[str, Any]]:
    initial = log.initial_parameters or {}
    changed = {item[1]: item[2] for item in (log.changed_parameters or []) if len(item) >= 3}
    result = []
    for item in GLOSSARY[group]:
        name = item["name"]
        if name in initial or name in changed:
            entry = dict(item)
            entry["value"] = changed.get(name, initial.get(name))
            result.append(entry)
    return result


def _unavailable(metric_id: str, name: str, reason: str, log: ULog) -> dict[str, Any]:
    return {
        "id": metric_id,
        "name": name,
        "status": "unavailable",
        "label": "数据不足",
        "summary": reason,
        "details": [reason],
        "evidence": [],
        "series": [],
        "data_sources": [],
        "parameters": _parameters(log, metric_id),
    }


def _vibration(log: ULog, start: int, end: int) -> dict[str, Any]:
    rules = RULES["vibration"]
    clip_count = 0
    data_sources = []
    clip_dataset = _dataset(log, "sensor_accel")
    has_clip_data = False
    for axis in range(3):
        _, values = _masked(clip_dataset, start, end, f"clip_counter[{axis}]")
        clean = _finite(values)
        if clean.size:
            has_clip_data = True
            clip_count += max(0, int(clean[-1] - clean[0]))
    if has_clip_data:
        data_sources.append(_source(
            "sensor_accel", "clip_counter[0..2]", "三轴加速度计削波累计计数", "次",
            "用飞行结束值减去开始值，判断传感器是否超过量程。",
        ))

    combined = _dataset(log, "sensor_combined")
    ts = _field(combined, "timestamp")
    axes = [_field(combined, f"accelerometer_m_s2[{i}]") for i in range(3)]
    accel_axis_rms = np.asarray([])
    rms_ts = np.asarray([])
    rms_axis_values: list[np.ndarray] = []
    if ts is not None and all(axis is not None for axis in axes):
        ts = np.asarray(ts, dtype=np.int64)
        mask = (ts >= start) & (ts <= end)
        ts = ts[mask]
        matrix = np.column_stack([np.asarray(axis, dtype=float)[mask] for axis in axes])
        if len(matrix) >= 20:
            # Adjacent-sample differences reject gravity and slow manoeuvres while retaining high-frequency motion.
            residual = np.diff(matrix, axis=0) / math.sqrt(2.0)
            accel_axis_rms = np.sqrt(np.mean(residual * residual, axis=0))
            chunk = max(10, len(residual) // 200)
            rms_axis_values = [
                np.asarray([np.sqrt(np.mean(residual[i:i + chunk, axis] ** 2)) for i in range(0, len(residual), chunk)])
                for axis in range(3)
            ]
            rms_ts = ts[1:][::chunk][: len(rms_axis_values[0])]
            data_sources.insert(0, _source(
                "sensor_combined", "accelerometer_m_s2[0..2]", "机体系 X/Y/Z 三轴加速度", "m/s²",
                "分别对 X、Y、Z 轴相邻采样差分，并计算各轴高频加速度 RMS。",
            ))

    est = _dataset(log, "estimator_status")
    vibe_p95 = []
    vibe_series = []
    for axis in range(3):
        vt, vv = _masked(est, start, end, f"vibe[{axis}]")
        if vv.size:
            vibe_p95.append(_percentile(np.abs(vv), 95))
            vibe_series.append(_series(f"EKF 振动 {axis + 1}", "", vt, vv, log.start_timestamp))
    if vibe_p95:
        data_sources.append(_source(
            "estimator_status", "vibe[0..2]", "EKF 圆锥、高频角增量和速度增量振动指标", "无统一单位",
            "分别取绝对值 P95，作为惯性估计受振动影响的辅助证据。",
        ))

    rank = 0
    reasons = []
    if clip_count >= rules["clip_severe_count"]:
        rank = 2
        reasons.append("加速度计发生大量削波")
    elif clip_count >= rules["clip_warning_count"]:
        rank = max(rank, 1)
        reasons.append("检测到加速度计削波")
    worst_axis = None
    if accel_axis_rms.size:
        worst_axis = int(np.argmax(accel_axis_rms))
        worst_value = float(accel_axis_rms[worst_axis])
        axis_name = "XYZ"[worst_axis]
        if worst_value >= rules["accel_axis_rms_severe_m_s2"]:
            rank = 2
            reasons.append(f"{axis_name} 轴高频加速度 RMS 达到严重阈值")
        elif worst_value >= rules["accel_axis_rms_warning_m_s2"]:
            rank = max(rank, 1)
            reasons.append(f"{axis_name} 轴高频加速度 RMS 偏大")
    for i, value in enumerate(vibe_p95):
        if value >= rules["vibe_severe"][i]:
            rank = 2
        elif value >= rules["vibe_warning"][i]:
            rank = max(rank, 1)

    if not accel_axis_rms.size and not vibe_p95 and clip_count == 0:
        return _unavailable("vibration", "机体振动", "日志缺少可用的加速度或 EKF 振动数据。", log)

    labels = ("正常", "偏大", "严重")
    summary = reasons[0] if reasons else "未发现明显高频振动或传感器削波"
    evidence = [_evidence("加速度计削波次数", clip_count, "次")]
    series = vibe_series
    if accel_axis_rms.size:
        axis_evidence = []
        for i, axis in enumerate("XYZ"):
            value = float(accel_axis_rms[i])
            axis_rank = 2 if value >= rules["accel_axis_rms_severe_m_s2"] else 1 if value >= rules["accel_axis_rms_warning_m_s2"] else 0
            item = _evidence(f"{axis} 轴高频加速度 RMS", value, "m/s²")
            item["status"] = _status(axis_rank)
            item["result"] = ("正常", "偏大", "严重")[axis_rank]
            axis_evidence.append(item)
        evidence = axis_evidence + evidence
        axis_series = [
            _series(f"{axis} 轴高频加速度 RMS", "m/s²", rms_ts, rms_axis_values[i], log.start_timestamp)
            for i, axis in enumerate("XYZ")
        ]
        series = axis_series + series
    for i, value in enumerate(vibe_p95):
        evidence.append(_evidence(f"EKF vibe[{i}] P95", value))
    return {
        "id": "vibration", "name": "机体振动", "status": _status(rank), "label": labels[rank],
        "summary": summary,
        "details": ["X/Y/Z 三轴分别计算，最终等级由 RMS 最大的轴决定。", "优先检查桨叶、机臂、飞控减振和螺丝松动。", "高频加速度 RMS 是本工具的辅助指标，需结合削波与 EKF 状态判断。"],
        "evidence": evidence, "series": series, "data_sources": data_sources, "parameters": _parameters(log, "vibration"),
    }


def _gps(log: ULog, start: int, end: int) -> dict[str, Any]:
    rules = RULES["gps"]
    gps = _dataset(log, "sensor_gps") or _dataset(log, "vehicle_gps_position")
    if gps is None:
        return _unavailable("gps", "GPS 状态", "日志中没有 GPS 主题。", log)
    ts, fix = _masked(gps, start, end, "fix_type")
    if fix.size == 0:
        return _unavailable("gps", "GPS 状态", "飞行阶段没有 GPS 定位数据。", log)
    fix_bad = float(np.mean(np.asarray(fix) < 3))
    _, sats = _masked(gps, start, end, "satellites_used")
    _, eph = _masked(gps, start, end, "eph")
    _, epv = _masked(gps, start, end, "epv")
    _, jam = _masked(gps, start, end, "jamming_state")
    _, spoof = _masked(gps, start, end, "spoofing_state")
    sats_p10, eph_p95, epv_p95 = _percentile(sats, 10), _percentile(eph, 95), _percentile(epv, 95)
    # SensorGps enum: 0=unknown, 1=OK/none, 2=warning/indicated, 3=critical/multiple.
    jammed = bool(_finite(jam).size and np.any(_finite(jam) >= 2))
    spoofed = bool(_finite(spoof).size and np.any(_finite(spoof) >= 2))
    rank = 0
    reasons = []
    if fix_bad >= rules["fix_bad_fraction_severe"] or (math.isfinite(eph_p95) and eph_p95 > rules["eph_severe_m"]) or jammed or spoofed:
        rank = 2
    elif fix_bad >= rules["fix_bad_fraction_warning"]:
        rank = 1
    if math.isfinite(sats_p10):
        rank = max(rank, 2 if sats_p10 < rules["satellites_severe"] else 1 if sats_p10 < rules["satellites_warning"] else 0)
    if math.isfinite(eph_p95):
        rank = max(rank, 2 if eph_p95 > rules["eph_severe_m"] else 1 if eph_p95 > rules["eph_warning_m"] else 0)
    if math.isfinite(epv_p95):
        rank = max(rank, 2 if epv_p95 > rules["epv_severe_m"] else 1 if epv_p95 > rules["epv_warning_m"] else 0)
    if fix_bad > 0:
        reasons.append(f"{fix_bad * 100:.1f}% 的样本未达到 3D 定位")
    if jammed:
        reasons.append("日志报告 GPS 干扰状态")
    if spoofed:
        reasons.append("日志报告 GPS 欺骗状态")
    labels = ("良好", "较差", "异常")
    evidence = [_evidence("非 3D 定位占比", fix_bad * 100, "%")]
    if math.isfinite(sats_p10): evidence.append(_evidence("卫星数 P10", sats_p10, "颗"))
    if math.isfinite(eph_p95): evidence.append(_evidence("水平误差 EPH P95", eph_p95, "m"))
    if math.isfinite(epv_p95): evidence.append(_evidence("垂直误差 EPV P95", epv_p95, "m"))
    series = [_series("定位类型", "", ts, fix, log.start_timestamp)]
    for field, name, unit in (("satellites_used", "卫星数", "颗"), ("eph", "水平误差 EPH", "m"), ("epv", "垂直误差 EPV", "m")):
        ft, fv = _masked(gps, start, end, field)
        if fv.size: series.append(_series(name, unit, ft, fv, log.start_timestamp))
    return {
        "id": "gps", "name": "GPS 状态", "status": _status(rank), "label": labels[rank],
        "summary": reasons[0] if reasons else "飞行阶段保持 3D 定位，精度和卫星数处于首版建议范围",
        "details": ["EPH/EPV 越小越好；卫星数只是辅助指标，还要结合定位精度和干扰状态。"],
        "evidence": evidence, "series": series,
        "data_sources": [
            _source(gps.name, "fix_type", "GPS 定位类型", "枚举", "统计未达到 3D 定位的样本占比。"),
            _source(gps.name, "satellites_used", "参与定位的卫星数量", "颗", "使用 P10 反映飞行中较差时段的卫星数量。"),
            _source(gps.name, "eph / epv", "水平/垂直位置精度估计", "m", "使用 P95 判断飞行中较差时段的定位精度。"),
            _source(gps.name, "jamming_state / spoofing_state", "GPS 干扰/欺骗状态", "枚举", "检查接收机是否报告干扰或欺骗。只有接收机和 GNSS 模块具备干扰、欺骗检测能力时，这两个字段才有诊断意义。"),
        ],
        "parameters": _parameters(log, "gps"),
    }


def _battery(log: ULog, start: int, end: int) -> dict[str, Any]:
    rules = RULES["battery"]
    batteries = [d for d in log.data_list if d.name == "battery_status"]
    battery = next((d for d in batteries if _finite(_field(d, "voltage_v")).size and _percentile(_field(d, "voltage_v"), 50, 0) > 1), None)
    if battery is None:
        return _unavailable("battery", "电池压降", "日志中没有有效电池电压数据。", log)
    ts, voltage = _masked(battery, start, end, "voltage_v")
    _, current = _masked(battery, start, end, "current_a")
    _, cells = _masked(battery, start, end, "cell_count")
    _, warning = _masked(battery, start, end, "warning")
    _, cell_delta = _masked(battery, start, end, "max_cell_voltage_delta")
    valid_v = _finite(voltage)
    raw_cell_count = int(round(_percentile(cells, 50, 0)))
    cell_count = raw_cell_count
    cell_count_source = "日志"
    if valid_v.size >= 5 and raw_cell_count <= 1 and _percentile(valid_v, 50, 0) > 6:
        charged = float((log.initial_parameters or {}).get("BAT1_V_CHARGED", 4.2))
        if not 3.0 <= charged <= 4.5:
            charged = 4.2
        inferred = int(round(_percentile(valid_v, 95) / charged))
        if 2 <= inferred <= 14:
            cell_count = inferred
            cell_count_source = "按满电电压推断"
    if valid_v.size < 5 or cell_count <= 0:
        return _unavailable("battery", "电池压降", "缺少足够电压数据或无法确定电池串数。", log)
    per_cell = np.asarray(voltage, dtype=float) / cell_count
    sag = _percentile(per_cell, 90) - _percentile(per_cell, 10)
    delta_p95 = _percentile(cell_delta, 95)
    max_warning = int(_percentile(warning, 100, 0))
    rank = 0
    if sag >= rules["sag_severe_v_per_cell"] or max_warning >= 2 or (math.isfinite(delta_p95) and delta_p95 >= rules["cell_delta_severe_v"]):
        rank = 2
    elif sag >= rules["sag_warning_v_per_cell"] or max_warning >= 1 or (math.isfinite(delta_p95) and delta_p95 >= rules["cell_delta_warning_v"]):
        rank = 1
    resistance = math.nan
    current_arr = np.asarray(current, dtype=float)
    valid = np.isfinite(current_arr) & (current_arr >= 0) & np.isfinite(np.asarray(voltage, dtype=float))
    if np.count_nonzero(valid) >= 20 and np.ptp(current_arr[valid]) >= 2:
        time = (np.asarray(ts, dtype=float)[valid] - ts[valid][0]) / 1e6
        design = np.column_stack([np.ones_like(time), time, current_arr[valid]])
        coef, *_ = np.linalg.lstsq(design, np.asarray(voltage, dtype=float)[valid], rcond=None)
        resistance = max(0.0, float(-coef[2] / cell_count))
    labels = ("正常", "明显", "严重")
    summary = "电压随负载和放电的变化处于首版建议范围" if rank == 0 else "单体电压变化或飞控电池告警达到关注阈值"
    evidence = [_evidence("单体电压 P90-P10", sag, "V"), _evidence(f"电池串数（{cell_count_source}）", cell_count, "S"), _evidence("最高告警等级", max_warning)]
    if math.isfinite(delta_p95): evidence.append(_evidence("单体压差 P95", delta_p95, "V"))
    if math.isfinite(resistance): evidence.append(_evidence("估算单体动态内阻", resistance, "Ω"))
    return {
        "id": "battery", "name": "电池压降", "status": _status(rank), "label": labels[rank],
        "summary": summary,
        "details": ["P90-P10 同时包含负载压降与飞行期间的自然放电，不能单独等同于电池内阻。", "若日志记录了有效电流，动态内阻仅作为趋势参考。"],
        "evidence": evidence,
        "series": [_series("单体电压", "V", ts, per_cell, log.start_timestamp)] + ([_series("电流", "A", ts, current_arr, log.start_timestamp)] if current_arr.size == ts.size else []),
        "data_sources": [
            _source("battery_status", "voltage_v", "电池包总电压", "V", "除以电池串数后计算单体电压变化。"),
            _source("battery_status", "current_a", "电池电流", "A", "数据有效时用于估算动态内阻趋势。"),
            _source("battery_status", "cell_count", "电池串数", "S", "用于把总电压换算为单体电压；异常时会明确标注推断值。"),
            _source("battery_status", "warning / max_cell_voltage_delta", "电池告警/最大单体压差", "枚举 / V", "作为压降结论的附加严重度证据。"),
        ],
        "parameters": _parameters(log, "battery"),
    }


def _quat_matrix(dataset, prefix: str) -> np.ndarray | None:
    axes = [_field(dataset, f"{prefix}[{i}]") for i in range(4)]
    if not all(axis is not None for axis in axes):
        return None
    matrix = np.column_stack(axes).astype(float)
    norms = np.linalg.norm(matrix, axis=1)
    valid = norms > 1e-9
    matrix[valid] /= norms[valid, None]
    return matrix


def _quat_to_euler_deg(quaternions: np.ndarray) -> np.ndarray:
    """Convert PX4 [w, x, y, z] quaternions to roll, pitch, yaw for display."""
    w, x, y, z = (quaternions[:, i] for i in range(4))
    roll = np.arctan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = np.arcsin(np.clip(2 * (w * y - z * x), -1.0, 1.0))
    yaw = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    angles = np.column_stack([roll, pitch, yaw])
    angles[:, 0] = np.unwrap(angles[:, 0])
    angles[:, 2] = np.unwrap(angles[:, 2])
    return np.degrees(angles)


def _attitude(log: ULog, start: int, end: int) -> dict[str, Any]:
    rules = RULES["attitude"]
    actual = _dataset(log, "vehicle_attitude")
    desired = _dataset(log, "vehicle_attitude_setpoint")
    at, dt = _field(actual, "timestamp"), _field(desired, "timestamp")
    aq, dq = _quat_matrix(actual, "q"), _quat_matrix(desired, "q_d")
    if at is None or dt is None or aq is None or dq is None or len(at) < 5 or len(dt) < 5:
        return _unavailable("attitude", "姿态跟踪", "日志缺少实际姿态或姿态设定值四元数。", log)
    at, dt = np.asarray(at, dtype=np.int64), np.asarray(dt, dtype=np.int64)
    mask = (at >= start) & (at <= end)
    at, aq = at[mask], aq[mask]
    if len(at) < 5:
        return _unavailable("attitude", "姿态跟踪", "飞行阶段的姿态样本不足。", log)
    # q and -q describe the same attitude; keep setpoint signs continuous before interpolation.
    dq = dq.copy()
    for i in range(1, len(dq)):
        if np.dot(dq[i - 1], dq[i]) < 0:
            dq[i] *= -1
    interp = np.column_stack([np.interp(at, dt, dq[:, i]) for i in range(4)])
    interp /= np.maximum(np.linalg.norm(interp, axis=1)[:, None], 1e-9)
    dots = np.clip(np.abs(np.sum(aq * interp, axis=1)), 0, 1)
    error = np.degrees(2 * np.arccos(dots))
    p95, maximum = _percentile(error, 95), _percentile(error, 100)
    actual_euler = _quat_to_euler_deg(aq)
    desired_euler = _quat_to_euler_deg(interp)
    # Put wrapped roll/yaw setpoints on the same displayed revolution as the actual angle.
    for axis in (0, 2):
        desired_euler[:, axis] += 360.0 * round((actual_euler[0, axis] - desired_euler[0, axis]) / 360.0)
    axis_error = np.abs((actual_euler - desired_euler + 180.0) % 360.0 - 180.0)
    axis_p95 = np.percentile(axis_error, 95, axis=0)
    rank = 0
    if p95 >= rules["p95_severe_deg"] or maximum >= rules["max_severe_deg"]:
        rank = 2
    elif p95 >= rules["p95_warning_deg"] or maximum >= rules["max_warning_deg"]:
        rank = 1
    labels = ("良好", "偏差较大", "严重偏差")
    axis_names = ("横滚", "俯仰", "偏航")
    evidence = [_evidence("四元数综合误差 P95", p95, "°"), _evidence("四元数最大综合误差", maximum, "°")]
    evidence.extend(_evidence(f"{axis_names[i]}误差 P95", float(axis_p95[i]), "°") for i in range(3))
    series = [
        _multi_series(
            f"{axis_names[i]}姿态",
            "°",
            at,
            (("实际", actual_euler[:, i]), ("目标", desired_euler[:, i])),
            log.start_timestamp,
        )
        for i in range(3)
    ]
    return {
        "id": "attitude", "name": "姿态跟踪", "status": _status(rank), "label": labels[rank],
        "summary": f"横滚/俯仰/偏航误差 P95：{axis_p95[0]:.1f}° / {axis_p95[1]:.1f}° / {axis_p95[2]:.1f}°",
        "details": ["健康等级仍使用实际与目标四元数的综合夹角，避免欧拉角跨越 ±180° 时产生假误差。", "展示曲线转换为横滚、俯仰、偏航三轴姿态角，每张图同时显示实际值与目标值。", "曲线中的尖峰需结合设定值变化判断是否为超调。"],
        "evidence": evidence,
        "series": series,
        "data_sources": [
            _source("vehicle_attitude.q / vehicle_attitude_setpoint.q_d", "roll / roll_sp（派生）", "实际/目标横滚角", "°", "实际横滚角由 q[0..3] 转换，目标横滚角由 q_d[0..3] 转换。"),
            _source("vehicle_attitude.q / vehicle_attitude_setpoint.q_d", "pitch / pitch_sp（派生）", "实际/目标俯仰角", "°", "实际俯仰角由 q[0..3] 转换，目标俯仰角由 q_d[0..3] 转换。"),
            _source("vehicle_attitude.q / vehicle_attitude_setpoint.q_d", "yaw / yaw_sp（派生）", "实际/目标偏航角", "°", "实际偏航角由 q[0..3] 转换，目标偏航角由 q_d[0..3] 转换，并处理 ±180° 显示跳变。"),
            _source("vehicle_attitude / vehicle_attitude_setpoint", "q[0..3] / q_d[0..3]", "实际/目标姿态四元数", "无量纲", "直接计算不受欧拉角跳变影响的三轴综合姿态误差。"),
        ],
        "parameters": _parameters(log, "attitude"),
    }


def _motors(log: ULog, start: int, end: int) -> dict[str, Any]:
    rules = RULES["motors"]
    motors = _dataset(log, "actuator_motors")
    ts = _field(motors, "timestamp")
    if motors is None or ts is None:
        return _unavailable("motors", "电机输出余量", "日志缺少归一化 actuator_motors 数据。", log)
    columns = []
    for i in range(12):
        values = _field(motors, f"control[{i}]")
        if values is not None and _finite(values).size:
            columns.append(np.asarray(values, dtype=float))
    if not columns:
        return _unavailable("motors", "电机输出余量", "actuator_motors 中没有有效电机通道。", log)
    ts = np.asarray(ts, dtype=np.int64)
    matrix = np.column_stack(columns)
    mask = (ts >= start) & (ts <= end)
    ts, matrix = ts[mask], matrix[mask]
    active = np.any(np.isfinite(matrix) & (matrix >= 0), axis=0)
    matrix = matrix[:, active]
    if matrix.size == 0:
        return _unavailable("motors", "电机输出余量", "飞行阶段没有有效电机输出。", log)
    per_sample = np.nanmax(np.where(matrix >= 0, matrix, np.nan), axis=1)
    p95, maximum = _percentile(per_sample, 95), _percentile(per_sample, 100)
    saturation_fraction = float(np.mean(per_sample >= rules["saturation_level"]))
    rank = 0
    if p95 >= rules["p95_severe"] or saturation_fraction >= rules["saturation_fraction_severe"]:
        rank = 2
    elif p95 >= rules["p95_warning"] or saturation_fraction >= rules["saturation_fraction_warning"]:
        rank = 1
    labels = ("正常", "接近饱和", "饱和风险高")
    margin = max(0.0, (1.0 - p95) * 100)
    return {
        "id": "motors", "name": "电机输出余量", "status": _status(rank), "label": labels[rank],
        "summary": f"按 P95 估算仍有 {margin:.1f}% 输出余量",
        "details": [
            "使用归一化电机输出判断，不使用姿态控制量代替电机输出。",
            "时刻最大电机输出：在每个采样时刻，对所有有效电机 control 通道取最大值。",
            "时刻最大电机输出 P95：对上述时间序列取第 95 百分位，忽略最高 5% 的短暂尖峰，用于估算持续输出余量。",
            "全程瞬时最大输出：上述时间序列在整个飞行阶段的最大值，容易受起飞或急动作的单次尖峰影响。",
            "P95 达到 80% 判为接近饱和，达到 95% 判为高风险；输出不低于 95% 的时间占比达到 1%/5% 时也分别触发提醒/严重。",
        ],
        "evidence": [_evidence("时刻最大电机输出 P95", p95 * 100, "%"), _evidence("全程瞬时最大输出", maximum * 100, "%"), _evidence("≥95% 输出占比", saturation_fraction * 100, "%")],
        "series": [_series("各时刻最大电机输出", "%", ts, per_sample * 100, log.start_timestamp)],
        "data_sources": [
            _source("actuator_motors", "control[0..11]", "归一化电机输出命令", "-1～1", "取有效电机通道的逐时刻最大值，计算 P95、峰值和饱和占比。"),
        ],
        "parameters": _parameters(log, "motors"),
    }


def _vehicle_type(log: ULog) -> tuple[str, bool]:
    status = _dataset(log, "vehicle_status")
    values = _finite(_field(status, "vehicle_type"))
    vtol = _finite(_field(status, "is_vtol"))
    if vtol.size and np.any(vtol > 0):
        return "VTOL", False
    if values.size:
        value = int(values[-1])
        mapping = {0: "未知", 1: "多旋翼", 2: "固定翼", 3: "地面车辆", 4: "飞艇"}
        return mapping.get(value, f"类型 {value}"), value in (0, 1)
    return "未记录", True


def analyze_ulog(path: str | Path, display_name: str | None = None) -> dict[str, Any]:
    path = Path(path)
    try:
        log = ULog(str(path), TOPICS)
    except Exception as exc:
        raise AnalysisError(f"无法解析 ULog：{exc}") from exc
    if log.last_timestamp <= log.start_timestamp:
        raise AnalysisError("日志中没有可分析的时序数据。")
    vehicle, supported = _vehicle_type(log)
    if not supported:
        raise AnalysisError(f"检测到{vehicle}日志；首版仅支持 PX4 多旋翼。")
    start, end, scope, has_flight = _flight_window(log)
    metrics = []
    analyzers = (
        (_vibration, "vibration", "机体振动"),
        (_gps, "gps", "GPS 状态"),
        (_battery, "battery", "电池压降"),
        (_attitude, "attitude", "姿态跟踪"),
        (_motors, "motors", "电机输出余量"),
    )
    for function, metric_id, name in analyzers:
        if not has_flight:
            metrics.append(_unavailable(metric_id, name, "未检测到有效飞行阶段，不能给出飞行健康结论。", log))
            continue
        try:
            metrics.append(function(log, start, end))
        except Exception as exc:
            metrics.append(_unavailable(metric_id, name, f"该项计算失败：{exc}", log))
    from .candidate_v2 import RULES as CANDIDATE_RULES, analyze_candidate_v2
    candidate_metrics = analyze_candidate_v2(log, start, end, metrics, has_flight)
    for metric in metrics:
        candidate = candidate_metrics.get(metric["id"])
        metric["candidate_v2"] = candidate
        if metric["status"] == "unavailable":
            metric["rule_hits"] = []
        elif metric["status"] == "normal":
            metric["rule_hits"] = ["未触发 v1.2.0 的提醒或严重阈值。"]
        else:
            metric["rule_hits"] = [metric["summary"]]
        metric["data_quality"] = candidate.get("data_quality", {}) if candidate else {}
        metric["anomaly_windows"] = candidate.get("anomaly_windows", []) if candidate else []
    status_rank = {"normal": 0, "unavailable": 0, "warning": 1, "severe": 2}
    overall_rank = max((status_rank[item["status"]] for item in metrics), default=0)
    unavailable_count = sum(item["status"] == "unavailable" for item in metrics)
    if overall_rank == 2:
        overall = "存在严重风险项目"
    elif overall_rank == 1:
        overall = "存在需要关注的项目"
    elif unavailable_count == len(metrics):
        overall = "数据不足，无法完成飞行检查"
    elif unavailable_count:
        overall = "已完成部分检查，部分数据不足"
    else:
        overall = "未发现明显异常"
    return {
        "meta": {
            "filename": display_name or path.name,
            "duration_s": round((log.last_timestamp - log.start_timestamp) / 1e6, 1),
            "flight_duration_s": round(max(0, end - start) / 1e6, 1),
            "vehicle_type": vehicle,
            "px4_version": str(log.msg_info_dict.get("ver_sw", "未记录")),
            "scope": scope,
            "rule_version": RULES["version"],
            "algorithm_version": "v1.0.0",
            "candidate_algorithm_version": CANDIDATE_RULES["version"],
        },
        "overall": overall,
        "metrics": metrics,
        "disclaimer": "本结果仅供飞后维护排查，不能替代飞前检查、机体检查或飞行安全决策。",
    }
