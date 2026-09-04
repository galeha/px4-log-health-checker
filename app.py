from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread, Timer
from urllib.parse import unquote

from px4_health import AnalysisError, analyze_ulog
from px4_health.explorer import LogSessionStore


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_UPLOAD = 512 * 1024 * 1024
MAX_JSON_REQUEST = 1024 * 1024
SESSIONS = LogSessionStore()
CLIENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")


class BrowserClientTracker:
    def __init__(self, shutdown_callback, shutdown_delay: float = 3.0, timer_factory=Timer):
        self._shutdown_callback = shutdown_callback
        self._shutdown_delay = shutdown_delay
        self._timer_factory = timer_factory
        self._clients: set[str] = set()
        self._generation = 0
        self._lock = Lock()

    def register(self, client_id: str) -> int:
        with self._lock:
            self._clients.add(client_id)
            self._generation += 1
            return len(self._clients)

    def close(self, client_id: str) -> int:
        with self._lock:
            if client_id not in self._clients:
                return len(self._clients)
            self._clients.remove(client_id)
            self._generation += 1
            remaining = len(self._clients)
            generation = self._generation

        if remaining == 0:
            timer = self._timer_factory(
                self._shutdown_delay,
                self._shutdown_if_still_unused,
                args=(generation,),
            )
            timer.daemon = True
            timer.start()
        return remaining

    def _shutdown_if_still_unused(self, generation: int) -> None:
        with self._lock:
            if self._clients or generation != self._generation:
                return
        print("\n浏览器界面已关闭，正在停止本地服务……")
        self._shutdown_callback()


class HealthServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class):
        super().__init__(server_address, handler_class)
        self.browser_clients = BrowserClientTracker(self.shutdown)


def _read_exit_key() -> bool:
    """Wait for one console key and return whether a key was read."""
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.getwch()
            return True
        if sys.stdin.isatty():
            sys.stdin.read(1)
            return True
    except (EOFError, OSError):
        # Packaged smoke tests and redirected launches may not own a console.
        pass
    return False


def _stop_server_on_keypress(server: ThreadingHTTPServer) -> None:
    if _read_exit_key():
        print("\n正在停止本地服务……")
        server.shutdown()


class HealthHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def end_headers(self) -> None:
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

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
        if self.path == "/api/browser-open":
            self._browser_open()
            return
        if self.path == "/api/browser-close":
            self._browser_close()
            return
        if self.path == "/api/shutdown":
            self._shutdown()
            return
        if self.path == "/api/analyze":
            self._analyze()
            return
        if self.path == "/api/explorer-series":
            self._explorer_series()
            return
        self._json({"error": "接口不存在。"}, HTTPStatus.NOT_FOUND)

    def _small_json_request(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求长度无效。") from exc
        if length <= 0 or length > 4096:
            raise ValueError("请求内容无效。")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求格式无效。")
        return payload

    def _browser_client_id(self) -> str:
        client_id = str(self._small_json_request().get("client_id", ""))
        if not CLIENT_ID_PATTERN.fullmatch(client_id):
            raise ValueError("浏览器客户端标识无效。")
        return client_id

    def _browser_open(self) -> None:
        if self.headers.get("X-PX4-Health-Client") != "browser":
            self._json({"error": "浏览器请求验证失败。"}, HTTPStatus.FORBIDDEN)
            return
        try:
            count = self.server.browser_clients.register(self._browser_client_id())
            self._json({"ok": True, "browser_clients": count})
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _browser_close(self) -> None:
        try:
            count = self.server.browser_clients.close(self._browser_client_id())
            self._json({"ok": True, "browser_clients": count})
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _shutdown(self) -> None:
        if self.headers.get("X-PX4-Health-Client") != "browser":
            self._json({"error": "浏览器请求验证失败。"}, HTTPStatus.FORBIDDEN)
            return
        self._json({"ok": True})
        Thread(target=self.server.shutdown, daemon=True).start()

    def _analyze(self) -> None:
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
            result["explorer"] = SESSIONS.create(temp_path)
            temp_path = None  # The active explorer session now owns the file.
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

    def _explorer_series(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_JSON_REQUEST:
            self._json({"error": "曲线请求内容无效。"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise AnalysisError("曲线请求格式无效。")
            result = SESSIONS.query(
                str(payload.get("session_id", "")),
                payload.get("fields", []),
                payload.get("start_s"),
                payload.get("end_s"),
                payload.get("max_points", 4000),
            )
            self._json(result)
        except (AnalysisError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)
        except Exception as exc:
            self._json({"error": f"读取曲线失败：{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> None:
    host = os.environ.get("PX4_HEALTH_HOST", "127.0.0.1")
    port = int(os.environ.get("PX4_HEALTH_PORT", "8765"))
    url = f"http://{host}:{port}"
    server = HealthServer((host, port), HealthHandler)
    print(f"PX4 中文飞行健康检查器已启动：{url}")
    print("日志只在本机临时解析。按任意键停止并退出程序。")
    if os.environ.get("PX4_HEALTH_NO_BROWSER") != "1":
        Timer(0.8, lambda: webbrowser.open(url)).start()
    Thread(target=_stop_server_on_keypress, args=(server,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
        SESSIONS.close()


if __name__ == "__main__":
    main()
