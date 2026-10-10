"""Infrastructure for browser tests: a real Streamlit server, a fake Gemini endpoint and Playwright helpers."""

from __future__ import annotations

import glob
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
SECRET_ENV = ("GEMINI_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY", "GITHUB_TOKEN", "ADZUNA_APP_ID", "ADZUNA_APP_KEY")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AppServer:
    """`streamlit run app.py` in a scratch directory, with an explicit secrets file (never the developer's)."""

    def __init__(self, tmp: Path, secrets: dict[str, str] | None = None):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.log_path = tmp / "server.log"
        (tmp / ".streamlit").mkdir(exist_ok=True)
        (tmp / ".streamlit" / "config.toml").write_text((ROOT / ".streamlit" / "config.toml").read_text())
        secrets_file = tmp / "secrets.toml"
        secrets_file.write_text("".join(f'{k} = "{v}"\n' for k, v in (secrets or {}).items()))
        env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
        env["PYTHONPATH"] = str(ROOT)
        cmd = [
            sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
            "--server.port", str(self.port), "--server.headless", "true", "--server.fileWatcherType", "none",
            "--browser.gatherUsageStats", "false", "--secrets.files", str(secrets_file),
        ]  # fmt: skip
        self.log = self.log_path.open("w")
        self.proc = subprocess.Popen(cmd, cwd=tmp, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self._wait()

    def _wait(self) -> None:
        for _ in range(100):
            try:
                if urllib.request.urlopen(f"{self.url}/_stcore/health", timeout=1).status == 200:  # noqa: S310
                    return
            except OSError:
                time.sleep(0.3)
        raise RuntimeError("Streamlit did not start:\n" + self.log_path.read_text()[-2000:])

    def log_text(self) -> str:
        self.log.flush()
        return self.log_path.read_text()

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


class FakeGemini:
    """Answers generateContent by looking at which feature's system prompt arrived. Records every request."""

    def __init__(self, replies: dict[str, object]):
        self.replies, self.requests, self.fail = replies, [], False
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
                system = json.dumps(body.get("systemInstruction") or body.get("system_instruction") or "")
                outer.requests.append(
                    {
                        "path": self.path,
                        "system": system,
                        "body": json.dumps(body),
                        "key": self.headers.get("x-goog-api-key", ""),
                    }
                )
                if outer.fail:
                    return self._send(503, {"error": {"code": 503, "message": "unavailable", "status": "UNAVAILABLE"}})
                for marker, reply in outer.replies.items():
                    if marker in system:
                        text = reply if isinstance(reply, str) else json.dumps(reply)
                        return self._send(
                            200,
                            {
                                "candidates": [
                                    {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
                                ]
                            },
                        )
                self._send(
                    400,
                    {
                        "error": {
                            "code": 400,
                            "message": "no scripted reply for this prompt",
                            "status": "INVALID_ARGUMENT",
                        }
                    },
                )

            def _send(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def chromium_path() -> str | None:
    found = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")
    return found[0] if found else None
