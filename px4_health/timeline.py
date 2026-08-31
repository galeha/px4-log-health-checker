from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from pyulog.px4_events import PX4Events

from .px4_enums import NAV_STATE_ENUM, enum_label


PACKAGE_DIR = Path(__file__).resolve().parent
GLOSSARY = json.loads((PACKAGE_DIR / "event_glossary.json").read_text(encoding="utf-8"))
MAX_ITEMS = 1000
UNKNOWN_TITLE = "未提供中文解释"

LEVEL_SEVERITY = {
    "EMERGENCY": "severe", "ALERT": "severe", "CRITICAL": "severe", "ERROR": "severe",
    "WARNING": "warning", "NOTICE": "info", "INFO": "info", "DEBUG": "info", "PROTOCOL": "info",
}
ARMING_STATES = {0: "初始化", 1: "待命", 2: "已解锁", 3: "待命错误", 4: "关机", 5: "空中恢复"}

FLAG_TRANSLATIONS = {
    "angular_velocity_invalid": "角速度数据无效",
    "attitude_invalid": "姿态估计无效",
    "local_altitude_invalid": "本地高度无效",
    "local_position_invalid": "本地位置无效",
    "local_velocity_invalid": "本地速度无效",
    "global_position_invalid": "全局位置无效",
    "auto_mission_missing": "自动任务缺失",
    "offboard_control_signal_lost": "Offboard 控制信号丢失",
    "home_position_invalid": "家位置无效",
    "manual_control_signal_lost": "遥控或手动控制信号丢失",
    "gcs_connection_lost": "地面站连接丢失",
    "battery_warning": "电池状态告警",
    "battery_low_remaining_time": "电池剩余时间过低",
    "battery_unhealthy": "电池状态不健康",
    "geofence_breached": "突破地理围栏",
    "mission_failure": "任务执行失败",
    "wind_limit_exceeded": "超过风速限制",
    "flight_time_limit_exceeded": "超过飞行时间限制",
    "local_position_accuracy_low": "本地位置精度过低",
    "navigator_failure": "导航模块故障",
    "fd_critical_failure": "故障检测器报告严重故障",
    "fd_esc_arming_failure": "电调解锁失败",
    "fd_imbalanced_prop": "检测到桨叶不平衡",
    "fd_motor_failure": "检测到电机故障",
    "fd_roll": "横滚姿态超限",
    "fd_pitch": "俯仰姿态超限",
    "fd_alt": "高度状态异常",
    "fd_ext": "外部自动触发故障",
    "fd_arm_escs": "电调解锁状态异常",
    "fd_battery": "电池故障",
    "cs_mag_fault": "磁力计故障",
    "cs_gnss_yaw_fault": "GNSS 航向故障",
    "cs_ev_yaw_fault": "外部视觉航向故障",
    "cs_baro_fault": "气压计故障",
    "cs_rng_fault": "测距传感器故障",
    "cs_inertial_dead_reckoning": "进入惯性航位推算",
    "cs_wind_dead_reckoning": "进入风速航位推算",
}

CATEGORY_FIELDS = {
    "flight": ["vehicle_status[0].arming_state", "vehicle_status[0].nav_state", "vehicle_land_detected[0].landed"],
    "failsafe": ["vehicle_status[0].failsafe"],
    "gps": ["vehicle_gps_position[0].fix_type", "vehicle_gps_position[0].eph", "vehicle_gps_position[0].epv"],
    "battery": ["battery_status[0].voltage_v", "battery_status[0].current_a", "battery_status[0].remaining"],
    "estimator": ["estimator_status[0].innovation_test_ratio", "estimator_status_flags[0].cs_inertial_dead_reckoning"],
    "motor": [f"actuator_motors[0].control[{index}]" for index in range(4)],
    "control": ["vehicle_attitude[0].q[0]", "vehicle_attitude_setpoint[0].q_d[0]"],
    "sensor": ["sensor_accel[0].x", "sensor_accel[0].y", "sensor_accel[0].z"],
    "system": ["vehicle_status[0].nav_state", "vehicle_status[0].failsafe"],
}

MAGNETOMETER_FIELDS = [
    "vehicle_magnetometer[0].magnetometer_ga[0]",
    "vehicle_magnetometer[0].magnetometer_ga[1]",
    "vehicle_magnetometer[0].magnetometer_ga[2]",
    "estimator_status_flags[0].cs_mag_field_disturbed",
    "estimator_status_flags[0].cs_mag_fault",
    "estimator_status[0].mag_test_ratio",
    "battery_status[0].current_a",
    "battery_status[1].current_a",
    "actuator_motors[0].control[0]",
]


def _dataset(log, name: str):
    matches = [dataset for dataset in log.data_list if dataset.name == name]
    return max(matches, key=lambda item: len(item.data.get("timestamp", []))) if matches else None


def _clean_message(message: str) -> tuple[str, str]:
    original = str(message).rstrip("\t\r\n ")
    match = re.match(r"^\[([^]]+)]\s*(.*)$", original)
    return original, match.group(2).strip() if match else original


def _translate(message: str) -> tuple[str, bool]:
    original, content = _clean_message(message)
    unknown_event = re.fullmatch(r"\[Unknown event with ID ([0-9]+)]", original)
    if unknown_event:
        return f"无法解析的 PX4 事件（ID：{unknown_event.group(1)}）", False
    if content in GLOSSARY["exact"]:
        return GLOSSARY["exact"][content], True
    for item in GLOSSARY["patterns"]:
        if re.match(item["pattern"], content, flags=re.IGNORECASE):
            return re.sub(item["pattern"], item["replacement"], content, flags=re.IGNORECASE), True
    return UNKNOWN_TITLE, False


def _category(text: str) -> str:
    value = text.lower()
    if any(word in value for word in ("battery", "power")):
        return "battery"
    if any(word in value for word in ("gps", "gnss", "position", "geofence")):
        return "gps"
    if any(word in value for word in ("ekf", "estimator", "innovation", "mag", "baro", "range")):
        return "estimator"
    if any(word in value for word in ("motor", "esc", "prop")):
        return "motor"
    if any(word in value for word in ("accel", "gyro", "imu", "clipping")):
        return "sensor"
    if any(word in value for word in ("failsafe", "signal lost", "link lost", "mission fail", "failure", "kill", "termination")):
        return "failsafe"
    if any(word in value for word in ("arm", "takeoff", "land", "mission", "rtl", "loiter")):
        return "flight"
    return "system"


def _message_related_fields(message: str, category: str) -> list[str]:
    _, content = _clean_message(message)
    if any(word in content.lower() for word in ("mag", "magnetic", "compass")):
        return list(MAGNETOMETER_FIELDS)
    ekf_change = re.match(
        r"^primary EKF changed ([0-9]+) \(filter fault\) -> ([0-9]+)$",
        content,
        flags=re.IGNORECASE,
    )
    if ekf_change:
        previous, current = (int(ekf_change.group(1)), int(ekf_change.group(2)))
        return [
            "estimator_selector_status[0].primary_instance",
            f"estimator_status[{previous}].filter_fault_flags",
            f"estimator_status[{current}].filter_fault_flags",
        ]
    clipping = re.match(r"^(Accel|Gyro) ([0-9]+) clipping", content, flags=re.IGNORECASE)
    if not clipping:
        return list(CATEGORY_FIELDS.get(category, CATEGORY_FIELDS["system"]))
    topic = "sensor_accel" if clipping.group(1).lower() == "accel" else "sensor_gyro"
    instance = int(clipping.group(2))
    return [
        f"{topic}[{instance}].x",
        f"{topic}[{instance}].y",
        f"{topic}[{instance}].z",
        *[f"{topic}[{instance}].clip_counter[{axis}]" for axis in range(3)],
    ]


def _item(timestamp: int, origin: int, severity: str, category: str, title: str, original: str,
          source: str, important: bool, related_fields: Iterable[str] | None = None) -> dict[str, Any]:
    return {
        "time_s": round(max(0.0, (int(timestamp) - int(origin)) / 1e6), 3),
        "severity": severity,
        "category": category,
        "title": title,
        "original": original,
        "source": source,
        "important": bool(important),
        "count": 1,
        "related_fields": list(related_fields or CATEGORY_FIELDS.get(category, CATEGORY_FIELDS["system"])),
    }


def _message_items(log, origin: int) -> tuple[list[dict[str, Any]], bool, bool]:
    items = []
    for message in getattr(log, "logged_messages", []):
        original, _ = _clean_message(message.message)
        title, translated = _translate(original)
        level = message.log_level_str().upper()
        severity = LEVEL_SEVERITY.get(level, "info")
        category = _category(original)
        important = severity in {"warning", "severe"} or category == "failsafe"
        items.append(_item(message.timestamp, origin, severity, category, title, original, "logged_message", important,
                           _message_related_fields(original, category)))

    event_available = _dataset(log, "event") is not None
    embedded = "metadata_events" in getattr(log, "msg_info_multiple_dict", {})
    if event_available:
        decoder = PX4Events()
        decoder.set_default_json_definitions_cb(lambda _already_has_parser: None)
        for timestamp, level, message in decoder.get_logged_events(log):
            original, _ = _clean_message(message)
            title, translated = _translate(original)
            severity = LEVEL_SEVERITY.get(level.upper(), "info")
            category = _category(original)
            important = severity in {"warning", "severe"} or category == "failsafe"
            items.append(_item(timestamp, origin, severity, category, title, original, "event", important,
                               _message_related_fields(original, category)))
    return items, event_available, embedded


def _transitions(dataset, field: str) -> list[tuple[int, Any, Any]]:
    if dataset is None or "timestamp" not in dataset.data or field not in dataset.data:
        return []
    timestamps = np.asarray(dataset.data["timestamp"], dtype=np.int64)
    values = np.asarray(dataset.data[field])
    length = min(len(timestamps), len(values))
    if not length:
        return []
    timestamps, values = timestamps[:length], values[:length]
    result = []
    for index in range(1, length):
        before, after = values[index - 1], values[index]
        if bool(np.asarray(before != after).any()):
            result.append((int(timestamps[index]), before.item() if hasattr(before, "item") else before,
                           after.item() if hasattr(after, "item") else after))
    return result


def _status_items(log, origin: int) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    items = []
    coverage = {}
    status = _dataset(log, "vehicle_status")
    coverage["vehicle_status"] = status is not None
    if status is not None:
        arming = np.asarray(status.data.get("arming_state", []))
        timestamps = np.asarray(status.data.get("timestamp", []), dtype=np.int64)
        if len(arming) and int(arming[0]) == 2:
            items.append(_item(timestamps[0], origin, "info", "flight", "日志开始时飞行器已解锁", "arming_state=2", "vehicle_status.arming_state", True))
        for timestamp, before, after in _transitions(status, "arming_state"):
            state = ARMING_STATES.get(int(after), f"未知解锁状态（{int(after)}）")
            title = "飞行器已解锁" if int(after) == 2 else "飞行器已上锁" if int(before) == 2 else f"解锁状态变为：{state}"
            items.append(_item(timestamp, origin, "info", "flight", title, f"arming_state {int(before)} -> {int(after)}", "vehicle_status.arming_state", True))
        for timestamp, before, after in _transitions(status, "nav_state"):
            state = enum_label(NAV_STATE_ENUM, int(after), "未知模式")
            items.append(_item(timestamp, origin, "info", "flight", f"飞行模式切换为：{state}", f"nav_state {int(before)} -> {int(after)}", "vehicle_status.nav_state", True))
        for timestamp, _before, after in _transitions(status, "failsafe"):
            active = bool(after)
            items.append(_item(timestamp, origin, "severe" if active else "info", "failsafe",
                               "飞控进入失效保护" if active else "飞控退出失效保护",
                               f"failsafe={int(active)}", "vehicle_status.failsafe", True))
        failsafe_values = np.asarray(status.data.get("failsafe", []))
        if len(failsafe_values) and bool(failsafe_values[0]):
            items.append(_item(timestamps[0], origin, "severe", "failsafe", "日志开始时飞控已处于失效保护",
                               "failsafe=1", "vehicle_status.failsafe", True))

    landed = _dataset(log, "vehicle_land_detected")
    coverage["vehicle_land_detected"] = landed is not None
    for timestamp, _before, after in _transitions(landed, "landed"):
        active = bool(after)
        items.append(_item(timestamp, origin, "info", "flight", "检测到降落" if active else "检测到起飞",
                           f"landed={int(active)}", "vehicle_land_detected.landed", False))

    flag_sources = (
        ("failsafe_flags", "failsafe", "warning"),
        ("failure_detector_status", "failsafe", "severe"),
        ("estimator_status_flags", "estimator", "warning"),
    )
    for topic, category, active_severity in flag_sources:
        dataset = _dataset(log, topic)
        coverage[topic] = dataset is not None
        if dataset is None:
            continue
        for field in FLAG_TRANSLATIONS:
            if field not in dataset.data:
                continue
            values = np.asarray(dataset.data[field])
            topic_timestamps = np.asarray(dataset.data.get("timestamp", []), dtype=np.int64)
            seen_active = bool(len(values) and values[0]) and topic != "failsafe_flags"
            if seen_active and len(topic_timestamps):
                fields = list(MAGNETOMETER_FIELDS) if field.startswith("cs_mag") else [f"{topic}[{dataset.multi_id}].{field}"]
                items.append(_item(topic_timestamps[0], origin, active_severity, category,
                                   "日志开始时" + FLAG_TRANSLATIONS[field], f"{field}=1", f"{topic}.{field}", True, fields))
            for timestamp, _before, after in _transitions(dataset, field):
                active = bool(after)
                if not active and not seen_active:
                    continue
                title = FLAG_TRANSLATIONS[field] + ("已恢复" if not active else "")
                fields = list(MAGNETOMETER_FIELDS) if field.startswith("cs_mag") else [f"{topic}[{dataset.multi_id}].{field}"]
                items.append(_item(timestamp, origin, active_severity if active else "info", category, title,
                                   f"{field}={int(active)}", f"{topic}.{field}", True, fields))
                seen_active = active
    return items, coverage


def _collapse(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in sorted(items, key=lambda value: (value["time_s"], value["severity"], value["source"])):
        match = next((previous for previous in reversed(result[-8:])
                      if item["time_s"] - previous["time_s"] <= 1.0
                      and item["category"] == previous["category"]
                      and item["severity"] == previous["severity"]
                      and (item["original"] == previous["original"]
                           or (item["title"] != UNKNOWN_TITLE and item["title"] == previous["title"]))), None)
        if match is not None:
            match["count"] += 1
            match["important"] = match["important"] or item["important"]
            match["related_fields"] = list(dict.fromkeys(match["related_fields"] + item["related_fields"]))
            if match["source"] != item["source"]:
                match["source"] = "event + logged_message"
            continue
        result.append(item)
    return result


def build_timeline(log) -> dict[str, Any]:
    message_items, event_available, embedded = _message_items(log, log.start_timestamp)
    status_items, coverage = _status_items(log, log.start_timestamp)
    coverage.update({"logged_messages": bool(getattr(log, "logged_messages", [])), "event": event_available,
                     "embedded_event_metadata": embedded})
    all_items = _collapse(message_items + status_items)
    total_count = len(all_items)
    severe_count = sum(item["severity"] == "severe" for item in all_items)
    warning_count = sum(item["severity"] == "warning" for item in all_items)
    important_count = sum(item["important"] for item in all_items)
    failsafe_count = sum(item["category"] == "failsafe" and item["severity"] in {"warning", "severe"} for item in all_items)
    truncated = total_count > MAX_ITEMS
    if truncated:
        priority = {"severe": 0, "warning": 1, "info": 2}
        all_items = sorted(all_items, key=lambda item: (not item["important"], priority[item["severity"]], item["time_s"]))[:MAX_ITEMS]
        all_items.sort(key=lambda item: item["time_s"])
    missing = [name for name, available in coverage.items() if not available]
    return {
        "summary": {
            "total_count": total_count,
            "displayed_count": len(all_items),
            "important_count": important_count,
            "severe_count": severe_count,
            "warning_count": warning_count,
            "failsafe_count": failsafe_count,
        },
        "items": all_items,
        "coverage": coverage,
        "missing_sources": missing,
        "truncated": truncated,
        "offline_event_decoding": True,
    }
