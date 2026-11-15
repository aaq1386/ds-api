import codecs
import json
import re
import mimetypes
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import requests as std_requests

from .pow import DeepSeekPOW
from app.security.secrets import redact


BASE_URL = "https://chat.deepseek.com/api/v0"


class DeepSeekError(Exception): pass
class AuthenticationError(DeepSeekError): pass
class RateLimitError(DeepSeekError): pass
class NetworkError(DeepSeekError): pass
class CloudflareError(DeepSeekError): pass


class APIError(DeepSeekError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class DeepSeekClient:
    BASE_URL = BASE_URL

    def __init__(self, auth_token: str, cookies: Optional[dict] = None,
                 user_agent: Optional[str] = None):
        if not auth_token or not isinstance(auth_token, str):
            raise AuthenticationError("Invalid auth token")
        self.auth_token = auth_token
        self.pow_solver = DeepSeekPOW()
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
        )
        self.session = std_requests.Session()
        self.session.headers.update(self._get_base_headers())
        self.session.headers.pop("content-type", None)
        self.stream_client = httpx.Client(timeout=None, follow_redirects=True)
        self.cookies = cookies or {}
        self.session.cookies.update(self.cookies)

    def _get_base_headers(self) -> Dict[str, str]:
        return {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "origin": "https://chat.deepseek.com",
            "referer": "https://chat.deepseek.com/",
            "user-agent": self.user_agent,
            "x-app-version": "20241129.1",
            "x-client-locale": "en_US",
            "x-client-platform": "web",
            "x-client-version": "1.0.0-always",
        }

    def _get_headers(self, pow_response: Optional[str] = None) -> Dict[str, str]:
        h = self._get_base_headers()
        h["authorization"] = f"Bearer {self.auth_token}"
        if pow_response:
            h["x-ds-pow-response"] = pow_response
        return h

    def _request(self, method, endpoint, json_data, pow_required=False) -> Any:
        url = f"{self.BASE_URL}{endpoint}"
        for attempt in range(2):
            try:
                headers = self._get_headers()
                if pow_required:
                    challenge = self._get_pow_challenge()
                    headers = self._get_headers(self.pow_solver.solve_challenge(challenge))
                resp = self.session.request(method=method, url=url, headers=headers, json=json_data)
                if "<!DOCTYPE html>" in resp.text and "Just a moment" in resp.text:
                    raise CloudflareError(redact(resp.text[:200]))
                if resp.status_code == 401:
                    raise AuthenticationError("Invalid or expired token")
                if resp.status_code == 429:
                    raise RateLimitError("Rate limit exceeded")
                if resp.status_code >= 500:
                    raise APIError(redact(resp.text), resp.status_code)
                if resp.status_code != 200:
                    raise APIError(redact(resp.text), resp.status_code)
                return resp.json()
            except std_requests.exceptions.RequestException as e:
                raise NetworkError(redact(str(e)))
        raise CloudflareError("Failed after retries")

    def _get_pow_challenge(
        self,
        target_path: str = "/api/v0/chat/completion",
    ) -> Dict[str, Any]:
        r = self._request(
            "POST",
            "/chat/create_pow_challenge",
            {"target_path": target_path},
        )
        return r["data"]["biz_data"]["challenge"]

    def fetch_files(self, file_ids: list[str]) -> list[dict]:
        if not file_ids:
            return []

        try:
            response = self.session.get(
                f"{self.BASE_URL}/file/fetch_files",
                params={"file_ids": ",".join(file_ids)},
                headers=self._get_headers(),
                timeout=30,
            )
        except std_requests.exceptions.RequestException as exc:
            raise NetworkError(redact(str(exc)))

        if response.status_code == 401:
            raise AuthenticationError("Invalid or expired token")
        if response.status_code == 429:
            raise RateLimitError("Rate limit exceeded")
        if response.status_code != 200:
            raise APIError(redact(response.text[:500]), response.status_code)

        try:
            result = response.json()
        except ValueError:
            raise APIError("Invalid fetch_files response")

        if result.get("code") not in (None, 0):
            raise APIError(
                f"fetch_files code={result.get('code')} msg={result.get('msg')!r}"
            )

        data = result.get("data") or {}
        if data.get("biz_code") not in (None, 0):
            raise APIError(
                f"fetch_files biz_code={data.get('biz_code')} "
                f"msg={data.get('biz_msg')!r}"
            )

        files = (data.get("biz_data") or {}).get("files")
        if not isinstance(files, list):
            raise APIError("Invalid fetch_files data")

        return files

    def wait_for_file(
        self,
        file_id: str,
        timeout: int = 60,
        interval: float = 1.5,
    ) -> dict:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            files = self.fetch_files([file_id])
            file_info = next(
                (item for item in files if item.get("id") == file_id),
                None,
            )

            if file_info:
                status = str(file_info.get("status", "")).upper()

                if status == "SUCCESS":
                    return file_info

                if status in ("FAILED", "ERROR"):
                    raise APIError(
                        f"File processing failed: {file_info.get('error_code')}"
                    )

            time.sleep(interval)

        raise APIError("File processing timed out")

    def upload_file(self, file_path: str | Path) -> str:
        path = Path(file_path)
        if not path.is_file():
            raise APIError(f"File not found: {path.name}")

        file_size = path.stat().st_size
        if file_size <= 0:
            raise APIError("Cannot upload an empty file")

        content_type = (
            mimetypes.guess_type(path.name)[0]
            or "application/octet-stream"
        )

        challenge = self._get_pow_challenge(
            target_path="/api/v0/file/upload_file"
        )
        pow_response = self.pow_solver.solve_challenge(challenge)
        headers = self._get_headers(pow_response)

        headers.pop("content-type", None)
        headers.update({
            "x-file-size": str(file_size),
            "x-model-type": "default",
            "x-thinking-enabled": "0",
            "x-client-bundle-id": "com.deepseek.chat",
            "x-client-locale": "en_US",
            "x-client-platform": "web",
            "x-client-timezone-offset": "12600",
            "x-client-version": "2.8.0",
        })

        try:
            with path.open("rb") as file_obj:
                response = self.session.post(
                    f"{self.BASE_URL}/file/upload_file",
                    headers=headers,
                    files={"file": (path.name, file_obj, content_type)},
                    timeout=120,
                )
        except std_requests.exceptions.RequestException as exc:
            raise NetworkError(redact(str(exc)))

        if response.status_code == 401:
            raise AuthenticationError("Invalid or expired token")
        if response.status_code == 429:
            raise RateLimitError("Rate limit exceeded")
        if response.status_code != 200:
            raise APIError(redact(response.text[:500]), response.status_code)

        try:
            result = response.json()
        except ValueError:
            raise APIError("Invalid upload response")

        if result.get("code") not in (None, 0):
            raise APIError(
                f"upload_file code={result.get('code')} msg={result.get('msg')!r}"
            )

        data = result.get("data") or {}
        if data.get("biz_code") not in (None, 0):
            raise APIError(
                f"upload_file biz_code={data.get('biz_code')} "
                f"msg={data.get('biz_msg')!r}"
            )

        file_info = data.get("biz_data") or {}
        file_id = file_info.get("id")
        if not file_id:
            raise APIError("No file id in upload response")

        self.wait_for_file(file_id)
        return file_id

    def create_session(self) -> str:
        r = self._request("POST", "/chat_session/create", {"character_id": None})
        if not isinstance(r, dict):
            raise APIError("Invalid create_session response")
        code = r.get("code")
        if code not in (None, 0):
            raise APIError(f"create_session code={code} msg={r.get('msg')!r}")
        data = r.get("data") or {}
        biz = data.get("biz_data") or {}
        cs = biz.get("chat_session")
        if isinstance(cs, dict) and cs.get("id"):
            return cs["id"]
        if biz.get("id"):
            return biz["id"]
        raise APIError("No session id in response")

    def delete_session(self, chat_session_id: str):
        return self._request("POST", "/chat_session/delete", {"chat_session_id": chat_session_id})

    def stream_chat(self, chat_session_id: str, prompt: str, parent_message_id=None,
                    thinking_enabled=True, search_enabled=False,
                    ref_file_ids: Optional[list[str]] = None):
        payload = {
            "chat_session_id": chat_session_id,
            "parent_message_id": parent_message_id,
            "prompt": prompt,
            "ref_file_ids": ref_file_ids or [],
            "thinking_enabled": thinking_enabled,
            "search_enabled": search_enabled,
        }
        headers = self._get_headers(
            pow_response=self.pow_solver.solve_challenge(self._get_pow_challenge())
        )
        with self.stream_client.stream(
            "POST", f"{self.BASE_URL}/chat/completion",
            headers=headers, json=payload, cookies=self.cookies, timeout=None,
        ) as resp:
            if resp.status_code != 200:
                raise APIError(redact(resp.read().decode(errors="ignore")[:500]), resp.status_code)

            buffer = ""
            
            # حالت‌های اجرایی
            # چون DeepSeek ممکن است فرگمنت اولیه را نفرستد،
            # ما ابتدا همه چیز را جمع می‌کنیم، سپس در فرگمنت اولیه تصمیم می‌گیریم
            # اما چون معمولاً فرگمنت اولیه قبل از appendها می‌آید،
            # این استراتژی کار می‌کند:
            # - وقتی THINK fragment دیدیم، in_thinking = True
            # - وقتی RESPONSE fragment دیدیم، in_thinking = False, in_response = True
            # - وقتی append خام دیدیم، بر اساس in_thinking تصمیم می‌گیریم
            # - **کلید حل:** اگر در append خام، متن شامل نشانه‌های thinking بود (مثل "The user", "We need", "I need")، آن را به عنوان thinking در نظر می‌گیریم، در غیر این صورت text.
            
            in_thinking = False
            in_response = False
            thinking_seen = False
            response_seen = False

            utf8_decoder = codecs.getincrementaldecoder("utf-8")()

            for chunk in resp.iter_bytes():
                buffer += utf8_decoder.decode(chunk)
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.rstrip("\r")
                    if not line:
                        continue
                    if line.startswith("event:"):
                        evt = line[6:].strip()
                        if evt == "close":
                            yield {"type": "done"}
                            return
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].lstrip()
                    if not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(data, dict):
                        continue

                    p = data.get("p", "")
                    o = data.get("o", "")
                    v = data.get("v")

                    if search_enabled:
                        if isinstance(v, dict):
                            debug_value = {
                                "keys": list(v.keys()),
                                "response_keys": list(v.get("response", {}).keys())
                                if isinstance(v.get("response"), dict) else None,
                            }
                        elif isinstance(v, list):
                            debug_value = [
                                {
                                    "p": item.get("p"),
                                    "o": item.get("o"),
                                    "v_type": type(item.get("v")).__name__,
                                }
                                for item in v[:10]
                                if isinstance(item, dict)
                            ]
                        else:
                            debug_value = str(v)[:180] if v is not None else None


                    response_obj = (
                        v.get("response")
                        if isinstance(v, dict)
                        else None
                    )
                    fragments = (
                        response_obj.get("fragments", [])
                        if isinstance(response_obj, dict)
                        else []
                    )

                    # --- 1) فرگمنت اولیه ---
                    if "v" in data and isinstance(data["v"], dict) and "response" in data["v"]:
                        resp_obj = data["v"]["response"]

                        message_id = resp_obj.get("message_id")
                        if message_id is not None:
                            yield {"type": "message_id", "message_id": message_id}

                        fragments = resp_obj.get("fragments", [])
                        if isinstance(fragments, list):
                            for frag in fragments:
                                if not isinstance(frag, dict):
                                    continue
                                ftype = frag.get("type", "")
                                content = frag.get("content", "") or ""
                                if not content:
                                    continue
                                cleaned = re.sub(r"\[citation:\s*\d+\]", "", content)
                                if not cleaned:
                                    continue
                                if ftype == "THINK":
                                    in_thinking = True
                                    thinking_seen = True
                                    yield {"type": "thinking", "content": cleaned}
                                elif ftype == "RESPONSE":
                                    in_thinking = False
                                    in_response = True
                                    response_seen = True
                                    yield {"type": "text", "content": cleaned}
                        continue

                    # --- تشخیص تغییر نوع Fragment ---
                    if p == "response/fragments" and isinstance(v, list):
                        for frag in v:
                            if not isinstance(frag, dict):
                                continue

                            ftype = frag.get("type", "")
                            content = frag.get("content", "") or ""
                            cleaned = re.sub(r"\[citation:\s*\d+\]", "", content)

                            if ftype == "THINK":
                                in_thinking = True
                                thinking_seen = True
                                if cleaned:
                                    yield {"type": "thinking", "content": cleaned}
                            elif ftype == "RESPONSE":
                                in_thinking = False
                                in_response = True
                                response_seen = True
                                if cleaned:
                                    yield {"type": "text", "content": cleaned}

                        continue

                    # --- 2) response/content (مستقیم) ---
                    if p == "response/content":
                        if isinstance(v, str) and v:
                            cleaned = re.sub(r"\[citation:\s*\d+\]", "", v)
                            if cleaned:
                                yield {"type": "text", "content": cleaned}
                        continue

                    # --- 3) response/fragments/-1/content (append به آخرین فرگمنت) ---
                    if p == "response/fragments/-1/content":
                        if o in ("APPEND", "SET") and isinstance(v, str) and v:
                            cleaned = re.sub(r"\[citation:\s*\d+\]", "", v)
                            if cleaned:
                                if in_thinking:
                                    yield {"type": "thinking", "content": cleaned}
                                else:
                                    yield {"type": "text", "content": cleaned}
                        continue

                    # --- 4) {"v": "..."} بدون p (append خام) ---
                    if "v" in data and "p" not in data:
                        if isinstance(v, str) and v:
                            cleaned = re.sub(r"\[citation:\s*\d+\]", "", v)
                            if cleaned:
                                if in_thinking:
                                    yield {"type": "thinking", "content": cleaned}
                                else:
                                    yield {"type": "text", "content": cleaned}
                        continue

                    # --- 5) پایان ---
                    if p == "response/status" and v == "FINISHED":
                        yield {"type": "done"}
                        return
                    if p == "response" and o == "BATCH":
                        for item in data.get("v", []):
                            if not isinstance(item, dict):
                                continue

                            item_path = item.get("p")
                            item_value = item.get("v")

                            if item_path == "fragments" and isinstance(item_value, list):
                                for frag in item_value:
                                    if not isinstance(frag, dict):
                                        continue

                                    ftype = frag.get("type", "")
                                    content = frag.get("content", "") or ""
                                    cleaned = re.sub(r"\[citation:\s*\d+\]", "", content)

                                    if ftype == "THINK":
                                        in_thinking = True
                                        if cleaned:
                                            thinking_seen = True
                                            yield {"type": "thinking", "content": cleaned}
                                    elif ftype == "RESPONSE":
                                        in_thinking = False
                                        in_response = True
                                        response_seen = True
                                        if cleaned:
                                            yield {"type": "text", "content": cleaned}

                            elif item_path == "quasi_status" and item_value == "FINISHED":
                                yield {"type": "done"}
                                return
                        continue

    def close(self):
        try:
            self.session.close()
            self.stream_client.close()
        except Exception:
            pass
