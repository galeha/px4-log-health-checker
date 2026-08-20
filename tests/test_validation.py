import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from px4_health.validation import initialize_manifest, merge_manifests, recommend_thresholds, run_validation, sha256_file


def fake_result(v1="severe", candidate="warning"):
    metrics = []
    for metric_id in ("vibration", "gps", "battery", "attitude", "motors"):
        metrics.append({
            "id": metric_id,
            "status": v1,
            "rule_hits": ["测试规则"],
            "candidate_v2": {"status": candidate, "evidence": [{"label": "测试", "value": 1}]},
        })
    return {
        "meta": {"px4_version": "test", "vehicle_type": "多旋翼"},
        "metrics": metrics,
    }


class ValidationTests(unittest.TestCase):
    def test_initialize_manifest_keeps_labels_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "flight.ulg").write_bytes(b"ULog-test")
            output = root / "manifest.json"
            with patch("px4_health.validation.analyze_ulog", return_value=fake_result()):
                manifest = initialize_manifest(root, output)
            self.assertEqual(len(manifest["entries"]), 1)
            self.assertEqual(manifest["entries"][0]["review_status"], "pending")
            self.assertTrue(all(value == "unknown" for value in manifest["entries"][0]["labels"].values()))

    def test_validation_builds_v1_and_candidate_matrices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "flight.ulg"
            log_path.write_bytes(b"ULog-test")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({"entries": [{
                "id": "flight",
                "path": str(log_path),
                "sha256": sha256_file(log_path),
                "review_status": "reviewed",
                "labels": {metric: "severe" for metric in ("vibration", "gps", "battery", "attitude", "motors")},
            }]}), encoding="utf-8")
            output = root / "report.json"
            with patch("px4_health.validation.analyze_ulog", return_value=fake_result()):
                report = run_validation(manifest_path, output)
            self.assertEqual(report["reviewed_entries"], 1)
            self.assertEqual(report["matrices"]["v1"]["vibration"]["severe"]["severe"], 1)
            self.assertEqual(report["matrices"]["candidate_v2"]["vibration"]["severe"]["warning"], 1)
            self.assertTrue(report["quality"]["candidate_v2"]["acceptance"]["known_severe_never_normal"])

    def test_merge_manifests_deduplicates_and_keeps_pending_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.json"
            public = root / "public.json"
            output = root / "merged.json"
            base.write_text(json.dumps({"entries": [{"sha256": "a" * 64, "source": "user-local"}]}), encoding="utf-8")
            public.write_text(json.dumps({"entries": [
                {"sha256": "a" * 64, "source": "duplicate"},
                {"sha256": "b" * 64, "source": "px4-flight-review-public", "url": "https://review.px4.io/download?log=test"},
            ]}), encoding="utf-8")
            merged = merge_manifests(base, public, output)
            self.assertEqual(len(merged["entries"]), 2)
            self.assertEqual(merged["entries"][1]["review_status"], "pending")
            self.assertEqual(merged["entries"][1]["labels"]["vibration"], "unknown")

    def test_threshold_grid_prioritizes_no_severe_case_as_normal(self):
        labels_and_scores = [("normal", 1.0), ("normal", 1.2), ("warning", 2.0), ("severe", 3.0), ("severe", 4.0)]
        snapshots = []
        for index, (label, score) in enumerate(labels_and_scores):
            snapshots.append({
                "id": str(index),
                "review_status": "reviewed",
                "labels": {metric: label for metric in ("vibration", "gps", "battery", "attitude", "motors")},
                "candidate_evidence": {
                    "vibration": [{"key": "band_rms_p95_x", "value": score}],
                    "gps": [{"key": "invalid_fix_longest_s", "value": score}],
                    "battery": [{"key": "load_sag_v_per_cell", "value": score}],
                    "attitude": [{"key": "quaternion_error_p95_deg", "value": score}],
                    "motors": [{"key": "near_saturation_longest_s", "value": score}],
                },
            })
        result = recommend_thresholds(snapshots)
        self.assertEqual(result["vibration"]["status"], "recommended")
        self.assertLessEqual(result["vibration"]["warning_threshold"], 3.0)
        self.assertEqual(result["vibration"]["normal_false_severe_count"], 0)


if __name__ == "__main__":
    unittest.main()
