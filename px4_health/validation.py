from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analyzer import analyze_ulog


METRICS = ("vibration", "gps", "battery", "attitude", "motors")
STATUSES = ("normal", "warning", "severe", "unavailable")
CALIBRATION_KEYS = {
    "vibration": ("band_rms_p95_x", "band_rms_p95_y", "band_rms_p95_z"),
    "gps": ("invalid_fix_longest_s",),
    "battery": ("load_sag_v_per_cell",),
    "attitude": ("quaternion_error_p95_deg",),
    "motors": ("near_saturation_longest_s",),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def initialize_manifest(log_directory: Path, output: Path) -> dict[str, Any]:
    entries = []
    for path in sorted(log_directory.rglob("*.ulg")):
        result = analyze_ulog(path, path.name)
        entries.append({
            "id": sha256_file(path)[:16],
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "source": "user-local",
            "source_url": "",
            "license": "private",
            "px4_version": result["meta"]["px4_version"],
            "vehicle_type": result["meta"]["vehicle_type"],
            "review_status": "pending",
            "reviewer": "",
            "known_conditions": [],
            "labels": {metric: "unknown" for metric in METRICS},
            "evidence_notes": "",
        })
    manifest = {
        "schema_version": 1,
        "description": "PX4 多旋翼健康规则人工复核清单",
        "label_policy": "飞手或维护结论，并由 PX4 告警、传感器状态和曲线证据交叉确认",
        "entries": entries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def merge_manifests(base_path: Path, public_path: Path, output: Path) -> dict[str, Any]:
    base = json.loads(base_path.read_text(encoding="utf-8"))
    public = json.loads(public_path.read_text(encoding="utf-8"))
    entries, seen = [], set()
    for entry in [*base.get("entries", []), *public.get("entries", [])]:
        digest = str(entry.get("sha256", "")).lower()
        if not digest or digest in seen:
            continue
        seen.add(digest)
        normalized = dict(entry)
        normalized.setdefault("id", digest[:16])
        normalized.setdefault("source_url", normalized.pop("url", ""))
        normalized.setdefault("license", "unknown")
        normalized.setdefault("px4_version", "unknown")
        normalized.setdefault("vehicle_type", "多旋翼")
        normalized.setdefault("review_status", "pending")
        normalized.setdefault("reviewer", "")
        normalized.setdefault("known_conditions", [])
        normalized.setdefault("labels", {metric: "unknown" for metric in METRICS})
        normalized.setdefault("evidence_notes", "")
        entries.append(normalized)
    merged = {
        "schema_version": 1,
        "description": base.get("description", "PX4 多旋翼健康规则人工复核清单"),
        "label_policy": base.get("label_policy", "标签必须来自人工复核，不能使用规则输出作为真值"),
        "entries": entries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def _matrix() -> dict[str, dict[str, int]]:
    return {actual: {predicted: 0 for predicted in STATUSES} for actual in STATUSES}


def _resolve_path(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else manifest_path.parent / path


def _primary_score(metric: str, evidence: list[dict[str, Any]]) -> float | None:
    keyed = {item.get("key"): item.get("value") for item in evidence}
    values = [keyed.get(key) for key in CALIBRATION_KEYS[metric]]
    finite = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(value)]
    return max(finite) if finite else None


def recommend_thresholds(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    recommendations = {}
    for metric in METRICS:
        samples = []
        for snapshot in snapshots:
            if snapshot.get("review_status") != "reviewed":
                continue
            actual = snapshot.get("labels", {}).get(metric)
            score = _primary_score(metric, snapshot.get("candidate_evidence", {}).get(metric, []))
            if actual in {"normal", "warning", "severe"} and score is not None:
                samples.append((score, actual))
        labels = {actual for _, actual in samples}
        if len(samples) < 5 or not {"normal", "severe"}.issubset(labels):
            recommendations[metric] = {
                "status": "insufficient_labels",
                "sample_count": len(samples),
                "reason": "至少需要 5 个已复核且同时包含正常和严重标签的有效样本。",
            }
            continue
        values = sorted({score for score, _ in samples})
        epsilon = max(1e-9, (values[-1] - values[0]) * 1e-6)
        candidates = [values[0] - epsilon]
        candidates.extend((left + right) / 2 for left, right in zip(values, values[1:]))
        candidates.append(values[-1] + epsilon)
        best = None
        for warning in candidates:
            for severe in candidates:
                if warning > severe:
                    continue
                predictions = ["severe" if score >= severe else "warning" if score >= warning else "normal" for score, _ in samples]
                severe_missed_as_normal = sum(actual == "severe" and predicted == "normal" for (_, actual), predicted in zip(samples, predictions))
                if severe_missed_as_normal:
                    continue
                normal_false_severe = sum(actual == "normal" and predicted == "severe" for (_, actual), predicted in zip(samples, predictions))
                mismatches = sum(actual != predicted for (_, actual), predicted in zip(samples, predictions))
                objective = (normal_false_severe, mismatches, severe, warning)
                if best is None or objective < best[0]:
                    best = (objective, warning, severe)
        recommendations[metric] = {
            "status": "recommended" if best else "no_feasible_thresholds",
            "sample_count": len(samples),
            "warning_threshold": round(best[1], 6) if best else None,
            "severe_threshold": round(best[2], 6) if best else None,
            "normal_false_severe_count": best[0][0] if best else None,
            "mismatch_count": best[0][1] if best else None,
            "primary_evidence_keys": list(CALIBRATION_KEYS[metric]),
            "experimental": True,
        }
    return recommendations


def run_validation(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matrices = {version: {metric: _matrix() for metric in METRICS} for version in ("v1", "candidate_v2")}
    snapshots = []
    reviewed = 0
    errors = []
    for entry in manifest.get("entries", []):
        path = _resolve_path(manifest_path, entry.get("path", ""))
        try:
            if not path.is_file():
                raise FileNotFoundError(f"日志不存在：{path}")
            actual_hash = sha256_file(path)
            if entry.get("sha256") and entry["sha256"].lower() != actual_hash:
                raise ValueError("SHA256 与清单不一致")
            result = analyze_ulog(path, path.name)
            metrics = {item["id"]: item for item in result["metrics"]}
            predictions = {
                "v1": {metric: metrics[metric]["status"] for metric in METRICS},
                "candidate_v2": {metric: metrics[metric]["candidate_v2"]["status"] for metric in METRICS},
            }
            is_reviewed = entry.get("review_status") == "reviewed"
            labels = entry.get("labels", {})
            if is_reviewed:
                reviewed += 1
                for metric in METRICS:
                    actual = labels.get(metric, "unknown")
                    if actual not in STATUSES:
                        continue
                    for version in predictions:
                        matrices[version][metric][actual][predictions[version][metric]] += 1
            snapshots.append({
                "id": entry.get("id", actual_hash[:16]),
                "sha256": actual_hash,
                "source": entry.get("source", "unknown"),
                "review_status": entry.get("review_status", "pending"),
                "labels": labels,
                "meta": result["meta"],
                "predictions": predictions,
                "rule_hits": {metric: metrics[metric].get("rule_hits", []) for metric in METRICS},
                "candidate_evidence": {metric: metrics[metric]["candidate_v2"].get("evidence", []) for metric in METRICS},
                "candidate_rule_hits": {metric: metrics[metric]["candidate_v2"].get("rule_hits", []) for metric in METRICS},
                "candidate_anomaly_windows": {metric: metrics[metric]["candidate_v2"].get("anomaly_windows", []) for metric in METRICS},
                "candidate_data_quality": {metric: metrics[metric]["candidate_v2"].get("data_quality", {}) for metric in METRICS},
            })
        except Exception as exc:
            errors.append({"id": entry.get("id", "unknown"), "path": str(path), "error": str(exc)})

    quality = {}
    for version, metric_matrices in matrices.items():
        known_severe = sum(sum(metric["severe"].values()) for metric in metric_matrices.values())
        detected_severe = sum(metric["severe"]["severe"] + metric["severe"]["warning"] for metric in metric_matrices.values())
        known_normal = sum(sum(metric["normal"].values()) for metric in metric_matrices.values())
        false_severe = sum(metric["normal"]["severe"] for metric in metric_matrices.values())
        quality[version] = {
            "known_severe_not_normal_rate_percent": round(100 * detected_severe / known_severe, 2) if known_severe else None,
            "known_normal_false_severe_rate_percent": round(100 * false_severe / known_normal, 2) if known_normal else None,
            "acceptance": {
                "known_severe_never_normal": known_severe > 0 and detected_severe == known_severe,
                "normal_false_severe_at_most_10_percent": known_normal > 0 and false_severe / known_normal <= 0.10,
            },
        }
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path.resolve()),
        "total_entries": len(manifest.get("entries", [])),
        "reviewed_entries": reviewed,
        "pending_entries": len(manifest.get("entries", [])) - reviewed,
        "matrices": matrices,
        "quality": quality,
        "calibration": recommend_thresholds(snapshots),
        "snapshots": snapshots,
        "errors": errors,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="PX4 健康规则真实日志验证工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="从日志目录建立待人工复核清单")
    init_parser.add_argument("--logs", required=True, type=Path)
    init_parser.add_argument("--output", type=Path, default=Path("validation/manifest.local.json"))
    run_parser = subparsers.add_parser("run", help="比较人工标签与 v1/候选 v2 结果")
    run_parser.add_argument("--manifest", required=True, type=Path)
    run_parser.add_argument("--output", type=Path, default=Path("validation/results/latest.json"))
    merge_parser = subparsers.add_parser("merge", help="将公开日志下载清单合并到本地人工复核清单")
    merge_parser.add_argument("--base", required=True, type=Path)
    merge_parser.add_argument("--public", required=True, type=Path)
    merge_parser.add_argument("--output", type=Path, default=Path("validation/manifest.local.json"))
    args = parser.parse_args()
    if args.command == "init":
        manifest = initialize_manifest(args.logs, args.output)
        print(f"已写入 {args.output}：{len(manifest['entries'])} 份日志待人工复核。")
    elif args.command == "run":
        report = run_validation(args.manifest, args.output)
        print(f"已写入 {args.output}：{report['reviewed_entries']}/{report['total_entries']} 份已复核，{len(report['errors'])} 个错误。")
    else:
        manifest = merge_manifests(args.base, args.public, args.output)
        print(f"已写入 {args.output}：共 {len(manifest['entries'])} 份日志。")


if __name__ == "__main__":
    main()
