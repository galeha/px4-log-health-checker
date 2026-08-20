from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


MAX_SIZE = 512 * 1024 * 1024
DBINFO_URL = "https://review.px4.io/dbinfo"
MULTICOPTER_TYPES = {"quadrotor", "hexarotor", "octorotor", "tricopter", "coaxial"}


def allowed_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "px4.io" or host.endswith(".px4.io"))


def download(url: str, output: Path) -> dict[str, str]:
    if not allowed_url(url):
        raise ValueError("只允许下载 https://*.px4.io 官方链接")
    request = urllib.request.Request(url, headers={"User-Agent": "px4-log-health-checker/validation"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, tempfile.NamedTemporaryFile(delete=False, suffix=".ulg") as handle:
        declared = int(response.headers.get("Content-Length", "0") or 0)
        if declared > MAX_SIZE:
            raise ValueError("日志超过 512 MB")
        stream = gzip.GzipFile(fileobj=response) if response.headers.get("Content-Encoding", "").lower() == "gzip" else response
        size = 0
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_SIZE:
                raise ValueError("日志超过 512 MB")
            digest.update(chunk)
            handle.write(chunk)
        temporary = Path(handle.name)
    try:
        with temporary.open("rb") as handle:
            header = handle.read(7)
        if header != b"ULog\x01\x12\x35":
            raise ValueError("下载内容不是有效 ULog 文件")
        sha256 = digest.hexdigest()
        output.mkdir(parents=True, exist_ok=True)
        destination = output / f"{sha256[:16]}.ulg"
        temporary.replace(destination)
        return {"path": str(destination.resolve()), "sha256": sha256, "source_url": url}
    finally:
        if temporary.exists():
            temporary.unlink()


def official_entries(count: int, good_count: int, max_duration: int = 600) -> list[dict[str, Any]]:
    request = urllib.request.Request(DBINFO_URL, headers={"User-Agent": "px4-log-health-checker/validation"})
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = response.read()
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            payload = gzip.decompress(payload)
        entries = json.loads(payload.decode("utf-8"))
    entries = [
        item for item in entries
        if str(item.get("mav_type", "")).lower() in MULTICOPTER_TYPES
        and 10 <= int(item.get("duration_s", 0) or 0) <= max_duration
        and allowed_url(str(item.get("download_url", "")))
    ]
    entries.sort(key=lambda item: item.get("log_date", ""), reverse=True)
    latest, vehicles = [], set()
    for item in entries:
        vehicle = item.get("vehicle_uuid") or item.get("log_id")
        if vehicle in vehicles:
            continue
        vehicles.add(vehicle)
        latest.append(item)
    good = [item for item in latest if str(item.get("rating", "")).lower() in {"good", "great"}]
    other = [item for item in latest if item not in good]
    selected = good[:min(good_count, count)]
    selected.extend(other[:count - len(selected)])
    if len(selected) < count:
        used = {item.get("log_id") for item in selected}
        selected.extend(item for item in latest if item.get("log_id") not in used and len(selected) < count)
    return [{
        "url": item["download_url"],
        "log_id": item.get("log_id", ""),
        "mav_type": item.get("mav_type", ""),
        "rating": item.get("rating", ""),
        "log_date": item.get("log_date", ""),
        "airframe_name": item.get("airframe_name", ""),
        "px4_version": item.get("ver_sw", ""),
        "duration_s": item.get("duration_s", 0),
    } for item in selected]


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 PX4 Flight Review 官方公开日志")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--urls", type=Path, help="逐行列出官方 ULog 下载链接")
    source.add_argument("--official-count", type=int, help="从 Flight Review 官方目录筛选指定数量的多旋翼日志")
    parser.add_argument("--good-count", type=int, default=15, help="批量模式中优先选择 Good/Great 的数量")
    parser.add_argument("--delay", type=float, default=6.0, help="官方下载之间的限速等待秒数")
    parser.add_argument("--max-duration", type=int, default=600, help="批量筛选的单份日志最长飞行秒数")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.urls:
        sources = [{"url": line.strip()} for line in args.urls.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    else:
        sources = official_entries(max(1, args.official_count), max(0, args.good_count), max(10, args.max_duration))
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "downloaded_manifest.json"
    entries, errors = [], []
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries = previous.get("entries", [])
            errors = previous.get("errors", [])
        except (OSError, json.JSONDecodeError):
            pass
    completed_urls = {item.get("source_url") or item.get("url") for item in entries}
    sources = [item for item in sources if item.get("url") not in completed_urls]
    for index, source_item in enumerate(sources):
        url = source_item["url"]
        try:
            item = download(url, args.output)
            item.update(source_item)
            item.update({
                "id": item["sha256"][:16],
                "source": "px4-flight-review-public",
                "license": "CC-BY PX4",
                "vehicle_type": "多旋翼",
                "review_status": "pending",
                "reviewer": "",
                "known_conditions": [],
                "labels": {metric: "unknown" for metric in ("vibration", "gps", "battery", "attitude", "motors")},
                "evidence_notes": "",
            })
            entries.append(item)
            print(f"已下载：{item['path']}", flush=True)
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)})
            print(f"下载失败：{url}：{exc}", flush=True)
        manifest_path.write_text(json.dumps({"schema_version": 1, "entries": entries, "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
        if index < len(sources) - 1 and args.delay > 0:
            time.sleep(args.delay)
    manifest = {"schema_version": 1, "entries": entries, "errors": errors}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"清单：{manifest_path}")


if __name__ == "__main__":
    main()
