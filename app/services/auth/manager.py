"""مدیریت Authentication: بارگذاری/ذخیره کوکی، اجرای Cloudflare bypass."""
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from app.config import settings
from app.security.secrets import redact


class AuthManager:
    def __init__(self, cookies_path: Optional[Path] = None,
                 server_script: Optional[Path] = None,
                 server_port: int = 8000):
        self.cookies_path = Path(cookies_path or settings.cookies_path)
        self.server_script = Path(server_script or settings.cloudflare_server_script)
        self.server_port = server_port
        self._server_proc: Optional[subprocess.Popen] = None

    def load_cookies(self) -> dict:
        if not self.cookies_path.exists():
            return {}
        try:
            data = json.loads(self.cookies_path.read_text(encoding="utf-8"))
            return data.get("cookies", {})
        except Exception as e:
            print(f"[AuthManager] failed to load cookies: {redact(str(e))}", file=sys.stderr)
            return {}

    def load_user_agent(self) -> str:
        if not self.cookies_path.exists():
            return ""
        try:
            data = json.loads(self.cookies_path.read_text(encoding="utf-8"))
            return data.get("user_agent", "")
        except Exception:
            return ""

    def save_cookies(self, cookies: dict, user_agent: str = "") -> None:
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"cookies": cookies, "user_agent": user_agent}
        self.cookies_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def refresh_via_cloudflare(self, target_url: str = "https://chat.deepseek.com",
                               timeout: int = 60) -> bool:
        if not self.server_script.exists():
            raise FileNotFoundError(f"cloudflare server script not found: {self.server_script}")
        self._start_server()
        try:
            return self._poll_and_save(target_url, timeout=timeout)
        finally:
            self._stop_server()

    def _start_server(self):
        self._server_proc = subprocess.Popen(
            [sys.executable, str(self.server_script), "--nolog"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(3)

    def _stop_server(self):
        if self._server_proc:
            try:
                self._server_proc.terminate()
                self._server_proc.wait(timeout=5)
            except Exception:
                try:
                    self._server_proc.kill()
                except Exception:
                    pass
            self._server_proc = None

    def _poll_and_save(self, target_url: str, timeout: int) -> bool:
        import requests
        url = f"http://127.0.0.1:{self.server_port}/cookies?url={target_url}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = requests.get(url, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    cookies = data.get("cookies", {})
                    if cookies.get("cf_clearance") or cookies.get("ds_session_id"):
                        self.save_cookies(cookies, data.get("user_agent", ""))
                        return True
            except Exception:
                pass
            time.sleep(2)
        return False
