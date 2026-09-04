from __future__ import annotations

import math
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import numpy as np
from pyulog import ULog

from .analyzer import AnalysisError
from .px4_enums import field_enum


MAX_FIELDS = 12
MAX_POINTS = 4000


_EXACT_UNITS = {
    ("sensor_accel", "x"): "m/s²",
    ("sensor_accel", "y"): "m/s²",
    ("sensor_accel", "z"): "m/s²",
    ("sensor_accel", "temperature"): "°C",
    ("sensor_accel", "timestamp_sample"): "µs",
    ("sensor_mag", "x"): "Gauss",
    ("sensor_mag", "y"): "Gauss",
    ("sensor_mag", "z"): "Gauss",
    ("sensor_mag", "temperature"): "°C",
    ("sensor_mag", "timestamp_sample"): "µs",
    ("vehicle_magnetometer", "magnetometer_ga[0]"): "Gauss",
    ("vehicle_magnetometer", "magnetometer_ga[1]"): "Gauss",
    ("vehicle_magnetometer", "magnetometer_ga[2]"): "Gauss",
    ("vehicle_magnetometer", "timestamp_sample"): "µs",
    ("sensor_gps", "eph"): "m",
    ("sensor_gps", "epv"): "m",
    ("vehicle_gps_position", "eph"): "m",
    ("vehicle_gps_position", "epv"): "m",
    ("failsafe_flags", "battery_warning"): "告警等级",
    ("estimator_status_flags", "cs_mag_field_disturbed"): "状态（0/1）",
    ("estimator_status_flags", "cs_mag_fault"): "状态（0/1）",
    ("estimator_status_flags", "cs_inertial_dead_reckoning"): "状态（0/1）",
    ("estimator_status", "mag_test_ratio"): "比值",
    ("vehicle_attitude_setpoint", "roll_body"): "rad",
    ("vehicle_attitude_setpoint", "pitch_body"): "rad",
    ("vehicle_attitude_setpoint", "yaw_body"): "rad",
    ("battery_status", "remaining"): "比例（0–1）",
}


def field_unit(topic: str, field: str) -> str:
    """Return only units that can be inferred without guessing semantics."""
    exact = _EXACT_UNITS.get((topic, field))
    if exact:
        return exact
    base = field.split("[")[0]
    if topic == "actuator_motors" and base == "control":
        return "归一化推力（-1～1）"
    if base.endswith("_counter") or base.endswith("_count") or base in {"samples", "error_count"}:
        return "次"
    suffixes = (
        ("_m_s2", "m/s²"), ("_rad_s", "rad/s"), ("_deg_s", "°/s"),
        ("_us", "µs"), ("_ms", "ms"), ("_hz", "Hz"),
        ("_deg", "°"), ("_rad", "rad"), ("_v", "V"), ("_a", "A"),
        ("_m", "m"), ("_s", "s"), ("_c", "°C"),
    )
    for suffix, unit in suffixes:
        if base.endswith(suffix):
            return unit
    return ""


def _is_curve_field(values: Any, timestamps: np.ndarray, field: str) -> bool:
    if field == "timestamp":
        return False
    array = np.asarray(values)
    return (
        array.ndim == 1
        and len(array) == len(timestamps)
        and (np.issubdtype(array.dtype, np.number) or np.issubdtype(array.dtype, np.bool_))
    )


@dataclass(frozen=True)
class _CurveSpec:
    dataset: Any
    source_field: str
    display_name: str
    unit: str
    bit_mask: int | None = None


def build_catalog(log: ULog) -> tuple[list[dict[str, Any]], dict[str, _CurveSpec]]:
    topics: list[dict[str, Any]] = []
    lookup: dict[str, _CurveSpec] = {}
    datasets = sorted(log.data_list, key=lambda item: (item.name.lower(), item.multi_id))
    for dataset in datasets:
        timestamps = np.asarray(dataset.data.get("timestamp", []))
        if timestamps.ndim != 1 or not len(timestamps):
            continue
        type_by_name = {
            item.field_name: item.type_str for item in getattr(dataset, "field_data", [])
        }
        fields = []
        for name in sorted(dataset.data, key=str.lower):
            values = dataset.data[name]
            if not _is_curve_field(values, timestamps, name):
                continue
            key = f"{dataset.name}[{dataset.multi_id}].{name}"
            unit = field_unit(dataset.name, name)
            field = {
                "key": key,
                "name": name,
                "type": type_by_name.get(name, str(np.asarray(values).dtype)),
                "unit": unit,
            }
            enum_metadata = field_enum(dataset.name, name)
            if enum_metadata:
                field["enum_title"] = enum_metadata["title"]
                field["enum_note"] = enum_metadata["note"]
                field["enum_kind"] = enum_metadata["kind"]
                field["enum_values"] = enum_metadata["values"]
            fields.append(field)
            lookup[key] = _CurveSpec(dataset, name, name, unit)
            if enum_metadata and enum_metadata["kind"] == "bitmask":
                for item in enum_metadata["values"]:
                    if not item["value"] or not item["derived_name"]:
                        continue
                    derived_name = f"{name}.{item['derived_name']}"
                    derived_key = f"{dataset.name}[{dataset.multi_id}].{derived_name}"
                    fields.append({
                        "key": derived_key,
                        "name": derived_name,
                        "type": "bool（派生）",
                        "unit": "状态（0/1）",
                        "derived": True,
                        "enum_title": item["label"],
                        "enum_note": f"从 {name} 的 {item['code']} 按位解码；0 表示未触发，1 表示故障存在。",
                        "enum_kind": "enum",
                        "enum_values": [
                            {"value": 0, "label": "未触发", "code": "false"},
                            {"value": 1, "label": "故障存在", "code": "true"},
                        ],
                    })
                    lookup[derived_key] = _CurveSpec(
                        dataset, name, derived_name, "状态（0/1）", int(item["value"]),
                    )
        if fields:
            topics.append({"name": dataset.name, "multi_id": dataset.multi_id, "fields": fields})
    return topics, lookup


def downsample_extrema(
    timestamps: np.ndarray, values: np.ndarray, max_points: int
) -> tuple[np.ndarray, np.ndarray]:
    """Downsample while retaining each time bucket's extrema in time order."""
    count = len(values)
    if count <= max_points:
        return timestamps, values
    bucket_count = max(1, (max_points - 2) // 2)
    edges = np.linspace(0, count, bucket_count + 1, dtype=int)
    selected = [0, count - 1]
    for start, end in zip(edges[:-1], edges[1:]):
        if end <= start:
            continue
        chunk = values[start:end]
        selected.extend((start + int(np.argmin(chunk)), start + int(np.argmax(chunk))))
    indices = np.unique(np.asarray(selected, dtype=int))
    if len(indices) > max_points:
        keep = np.linspace(0, len(indices) - 1, max_points, dtype=int)
        indices = indices[keep]
    return timestamps[indices], values[indices]


@dataclass
class _Session:
    session_id: str
    path: Path
    log: ULog
    lookup: dict[str, _CurveSpec]
    created_at: float


class LogSessionStore:
    """A single-user local store. Creating a session replaces the previous log."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._session: _Session | None = None

    def create(self, path: str | Path) -> dict[str, Any]:
        path = Path(path)
        try:
            log = ULog(str(path))
        except Exception as exc:
            raise AnalysisError(f"无法读取完整 ULog 字段：{exc}") from exc
        topics, lookup = build_catalog(log)
        session = _Session(uuid.uuid4().hex, path, log, lookup, time.time())
        with self._lock:
            previous = self._session
            self._session = session
        if previous:
            self._delete(previous.path)
        return {
            "session_id": session.session_id,
            "start_s": 0.0,
            "end_s": round((log.last_timestamp - log.start_timestamp) / 1e6, 6),
            "field_count": len(lookup),
            "topics": topics,
        }

    def query(
        self,
        session_id: str,
        field_keys: list[str],
        start_s: float | None,
        end_s: float | None,
        max_points: int = MAX_POINTS,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._session
        if not session or session.session_id != session_id:
            raise AnalysisError("日志会话已失效，请重新选择日志。")
        if not isinstance(field_keys, list) or any(not isinstance(key, str) for key in field_keys):
            raise AnalysisError("曲线字段列表格式无效。")
        if not field_keys:
            return {"start_s": 0.0, "end_s": 0.0, "series": []}
        if len(field_keys) > MAX_FIELDS:
            raise AnalysisError(f"一次最多显示 {MAX_FIELDS} 条曲线。")
        if len(set(field_keys)) != len(field_keys):
            raise AnalysisError("曲线字段不能重复。")
        unknown = [key for key in field_keys if key not in session.lookup]
        if unknown:
            raise AnalysisError(f"日志中不存在字段：{unknown[0]}")

        full_start = int(session.log.start_timestamp)
        full_end = int(session.log.last_timestamp)
        low = full_start if start_s is None else full_start + int(float(start_s) * 1e6)
        high = full_end if end_s is None else full_start + int(float(end_s) * 1e6)
        low, high = max(full_start, low), min(full_end, high)
        if not math.isfinite(float(low)) or not math.isfinite(float(high)) or high <= low:
            raise AnalysisError("曲线时间范围无效。")
        target = max(100, min(MAX_POINTS, int(max_points)))

        result = []
        for key in field_keys:
            spec = session.lookup[key]
            dataset = spec.dataset
            timestamps = np.asarray(dataset.data["timestamp"], dtype=np.int64)
            values = np.asarray(dataset.data[spec.source_field])
            if spec.bit_mask is not None:
                values = (values.astype(np.uint64, copy=False) & np.uint64(spec.bit_mask)) != 0
            mask = (timestamps >= low) & (timestamps <= high)
            timestamps, values = timestamps[mask], values[mask]
            if not len(values):
                points: list[list[float]] = []
            else:
                finite = np.isfinite(values.astype(float, copy=False))
                timestamps = timestamps[finite]
                values = values[finite].astype(float, copy=False)
                timestamps, values = downsample_extrema(timestamps, values, target)
                points = [
                    [round((int(timestamp) - full_start) / 1e6, 6), float(value)]
                    for timestamp, value in zip(timestamps, values)
                ]
            topic = dataset.name
            result.append({
                "key": key,
                "name": spec.display_name,
                "topic": topic,
                "multi_id": dataset.multi_id,
                "unit": spec.unit,
                "points": points,
            })
        return {
            "start_s": round((low - full_start) / 1e6, 6),
            "end_s": round((high - full_start) / 1e6, 6),
            "series": result,
        }

    def close(self) -> None:
        with self._lock:
            session = self._session
            self._session = None
        if session:
            self._delete(session.path)

    @staticmethod
    def _delete(path: Path) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass
