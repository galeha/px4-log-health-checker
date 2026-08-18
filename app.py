from __future__ import annotations

import json
import os
import tempfile
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Timer
from urllib.parse import unquote

from px4_health import AnalysisError, analyze_ulog


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_UPLOAD = 512 * 1024 * 1024


class HealthHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def _json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/health":
            self._json({"ok": True})
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/analyze":
            self._json({"error": "接口不存在。"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._json({"error": "没有收到日志文件。"}, HTTPStatus.BAD_REQUEST)
            return
        if length > MAX_UPLOAD:
            self._json({"error": "日志超过 512 MB，首版暂不支持。"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        filename = unquote(self.headers.get("X-Filename", "flight.ulg"))
        if not filename.lower().endswith(".ulg"):
            self._json({"error": "请选择 PX4 .ulg 日志。"}, HTTPStatus.BAD_REQUEST)
            return
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(prefix="px4-health-", suffix=".ulg", delete=False) as handle:
                temp_path = handle.name
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    handle.write(chunk)
                    remaining -= len(chunk)
            if remaining:
                raise AnalysisError("日志上传不完整。")
            result = analyze_ulog(temp_path, filename)
            self._json(result)
        except AnalysisError as exc:
            self._json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)
        except Exception as exc:
            self._json({"error": f"分析失败：{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> None:
    host = os.environ.get("PX4_HEALTH_HOST", "127.0.0.1")
    port = int(os.environ.get("PX4_HEALTH_PORT", "8765"))
    url = f"http://{host}:{port}"
    server = ThreadingHTTPServer((host, port), HealthHandler)
    print(f"PX4 中文飞行健康检查器已启动：{url}")
    print("按 Ctrl+C 停止。日志只在本机临时解析。")
    if os.environ.get("PX4_HEALTH_NO_BROWSER") != "1":
        Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
