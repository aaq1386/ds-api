import requests as std_requests
import httpx
from typing import Optional, Dict, Any, Generator, Literal
import json
from .pow import DeepSeekPOW
import sys
from pathlib import Path
import subprocess
import time
import re

ThinkingMode = Literal['detailed', 'simple', 'disabled']
SearchMode = Literal['enabled', 'disabled']

class DeepSeekError(Exception):
    pass

class AuthenticationError(DeepSeekError):
    pass

class RateLimitError(DeepSeekError):
    pass

class NetworkError(DeepSeekError):
    pass

class CloudflareError(DeepSeekError):
    pass

class APIError(DeepSeekError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code

class DeepSeekAPI:
    BASE_URL = "https://chat.deepseek.com/api/v0"

    def __init__(self, auth_token: str):
        if not auth_token or not isinstance(auth_token, str):
            raise AuthenticationError("Invalid auth token provided")

        self.auth_token = auth_token
        self.pow_solver = DeepSeekPOW()
        self.session = std_requests.Session()
        self.session.headers.update(self._get_base_headers())
        self.stream_client = httpx.Client(timeout=None, follow_redirects=True)

        cookies_path = Path(__file__).parent / 'cookies.json'
        try:
            with open(cookies_path, 'r') as f:
                cookie_data = json.load(f)
                self.cookies = cookie_data.get('cookies', {})
                self.session.cookies.update(self.cookies)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"\033[93mWarning: Could not load cookies from {cookies_path}: {e}\033[0m", file=sys.stderr)
            self.cookies = {}

    def _get_base_headers(self) -> Dict[str, str]:
        return {
            'accept': '*/*',
            'accept-language': 'en,fr-FR;q=0.9,fr;q=0.8,es-ES;q=0.7,es;q=0.6,en-US;q=0.5,am;q=0.4,de;q=0.3',
            'content-type': 'application/json',
            'origin': 'https://chat.deepseek.com',
            'referer': 'https://chat.deepseek.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'x-app-version': '20241129.1',
            'x-client-locale': 'en_US',
            'x-client-platform': 'web',
            'x-client-version': '1.0.0-always',
        }

    def _get_headers(self, pow_response: Optional[str] = None) -> Dict[str, str]:
        headers = self._get_base_headers()
        headers['authorization'] = f'Bearer {self.auth_token}'
        if pow_response:
            headers['x-ds-pow-response'] = pow_response
        return headers

    def _refresh_cookies(self) -> None:
        try:
            script_path = Path(__file__).parent / 'bypass.py'
            subprocess.run([sys.executable, script_path], check=True)
            time.sleep(2)
            cookies_path = Path(__file__).parent / 'cookies.json'
            with open(cookies_path, 'r') as f:
                cookie_data = json.load(f)
                self.cookies = cookie_data.get('cookies', {})
                self.session.cookies.update(self.cookies)
        except Exception as e:
            print(f"\033[93mWarning: Failed to refresh cookies: {e}\033[0m", file=sys.stderr)

    def _make_request(self, method: str, endpoint: str, json_data: Dict[str, Any], pow_required: bool = False) -> Any:
        url = f"{self.BASE_URL}{endpoint}"
        retry_count = 0
        max_retries = 2
        while retry_count < max_retries:
            try:
                headers = self._get_headers()
                if pow_required:
                    challenge = self._get_pow_challenge()
                    pow_response = self.pow_solver.solve_challenge(challenge)
                    headers = self._get_headers(pow_response)
                response = self.session.request(method=method, url=url, headers=headers, json=json_data)
                if "<!DOCTYPE html>" in response.text and "Just a moment" in response.text:
                    print("\033[93mWarning: Cloudflare protection detected. Bypassing...\033[0m", file=sys.stderr)
                    if retry_count < max_retries - 1:
                        self._refresh_cookies()
                        retry_count += 1
                        continue
                if response.status_code == 401:
                    raise AuthenticationError("Invalid or expired authentication token")
                elif response.status_code == 429:
                    raise RateLimitError("API rate limit exceeded")
                elif response.status_code >= 500:
                    raise APIError(f"Server error occurred: {response.text}", response.status_code)
                elif response.status_code != 200:
                    raise APIError(f"API request failed: {response.text}", response.status_code)
                return response.json()
            except std_requests.exceptions.RequestException as e:
                raise NetworkError(f"Network error occurred: {str(e)}")
            except json.JSONDecodeError:
                raise APIError("Invalid JSON response from server")
        raise APIError("Failed to bypass Cloudflare protection after multiple attempts")

    def _get_pow_challenge(self) -> Dict[str, Any]:
        try:
            response = self._make_request('POST', '/chat/create_pow_challenge', {'target_path': '/api/v0/chat/completion'})
            return response['data']['biz_data']['challenge']
        except KeyError:
            raise APIError("Invalid challenge response format from server")

    def create_chat_session(self) -> str:
        try:
            response = self._make_request('POST', '/chat_session/create', {'character_id': None})
            return response['data']['biz_data']['id']
        except KeyError:
            raise APIError("Invalid session creation response format from server")

    # ================== FINAL CORRECTED CHAT COMPLETION ==================
    def chat_completion(self,
                        chat_session_id: str,
                        prompt: str,
                        parent_message_id: Optional[str] = None,
                        thinking_enabled: bool = True,
                        search_enabled: bool = True) -> Generator[Dict[str, Any], None, None]:
        """
        Send a message and get streaming response.
        Yields {'type': 'text', 'content': str} for final answer only (no thinking).
        """
        if not prompt or not isinstance(prompt, str):
            raise ValueError("Prompt must be a non-empty string")
        if not chat_session_id or not isinstance(chat_session_id, str):
            raise ValueError("Chat session ID must be a non-empty string")

        json_data = {
            'chat_session_id': chat_session_id,
            'parent_message_id': parent_message_id,
            'prompt': prompt,
            'ref_file_ids': [],
            'thinking_enabled': thinking_enabled,
            'search_enabled': search_enabled,
        }

        try:
            headers = self._get_headers(
                pow_response=self.pow_solver.solve_challenge(self._get_pow_challenge())
            )

            with self.stream_client.stream(
                'POST',
                f"{self.BASE_URL}/chat/completion",
                headers=headers,
                json=json_data,
                cookies=self.cookies,
                timeout=None
            ) as response:
                if response.status_code != 200:
                    error_text = response.text
                    if response.status_code == 401:
                        raise AuthenticationError("Invalid or expired authentication token")
                    elif response.status_code == 429:
                        raise RateLimitError("API rate limit exceeded")
                    else:
                        raise APIError(f"API request failed: {error_text}", response.status_code)

                buffer = ""
                in_final_response = False   # becomes True when we start receiving the real answer

                for chunk in response.iter_bytes():
                    try:
                        buffer += chunk.decode('utf-8')
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.rstrip('\r')
                            if not line:
                                continue

                            # Skip event lines
                            if line.startswith('event:'):
                                continue

                            # Process only data lines
                            if not line.startswith('data:'):
                                continue

                            data_str = line[5:].lstrip()
                            if not data_str:
                                continue

                            if data_str == '[DONE]':
                                yield {'type': 'done', 'finish_reason': 'stop'}
                                return

                            try:
                                data = json.loads(data_str)

                                # --- Start of final response via response/content ---
                                if ('p' in data and data['p'] == 'response/content' and
                                    data.get('o') == 'APPEND'):
                                    in_final_response = True
                                    text = data.get('v', '')
                                    if text:
                                        text = re.sub(r'\[citation:\s*\d+\]', '', text)
                                        yield {'type': 'text', 'content': text, 'finish_reason': None}
                                    continue

                                # --- Start of final response via RESPONSE fragment (some languages) ---
                                if ('p' in data and data['p'] == 'response/fragments' and
                                    data.get('o') == 'APPEND'):
                                    fragments = data.get('v', [])
                                    for frag in fragments:
                                        if isinstance(frag, dict) and frag.get('type') == 'RESPONSE':
                                            in_final_response = True
                                            initial = frag.get('content', '')
                                            if initial:
                                                yield {'type': 'text', 'content': initial, 'finish_reason': None}
                                    continue

                                # --- Append to final response via path ---
                                if (in_final_response and 'p' in data and
                                    data['p'] == 'response/fragments/-1/content' and
                                    data.get('o') == 'APPEND'):
                                    text = data.get('v', '')
                                    if text:
                                        text = re.sub(r'\[citation:\s*\d+\]', '', text)
                                        yield {'type': 'text', 'content': text, 'finish_reason': None}
                                    continue

                                # --- Simple {"v": "..."} chunks belonging to final response ---
                                if in_final_response and 'v' in data and 'p' not in data:
                                    text = data['v']
                                    if isinstance(text, str) and text:
                                        text = re.sub(r'\[citation:\s*\d+\]', '', text)
                                        yield {'type': 'text', 'content': text, 'finish_reason': None}
                                    continue

                                # --- End of response ---
                                if ('p' in data and data['p'] == 'response/status' and
                                    data.get('v') == 'FINISHED'):
                                    yield {'type': 'done', 'finish_reason': 'stop'}
                                    return

                            except json.JSONDecodeError:
                                # ignore invalid JSON lines
                                pass

                    except Exception as e:
                        print(f"Error processing stream: {e}", file=sys.stderr)
                        continue

        except httpx.RequestError as e:
            raise NetworkError(f"Network error occurred during streaming: {str(e)}")
    # ================== END OF CHAT_COMPLETION ==================

    def chat_completion_simple(self, chat_session_id: str, prompt: str) -> str:
        full_response = ""
        for chunk in self.chat_completion(chat_session_id, prompt):
            if chunk.get('type') == 'text':
                content = chunk.get('content', '')
                if content:
                    full_response += content
                    print(content, end='', flush=True)
            if chunk.get('finish_reason') == 'stop':
                break
        print()
        return full_response
    
    def delete_chat_session(self, chat_session_id: str) -> Dict[str, Any]:
        """
        Delete a chat session by its ID.

        Args:
            chat_session_id: The ID of the chat session to delete.

        Returns:
            The JSON response from the server.
        """
        if not chat_session_id or not isinstance(chat_session_id, str):
            raise ValueError("chat_session_id must be a non-empty string")

        return self._make_request(
            method='POST',
            endpoint='/chat_session/delete',
            json_data={'chat_session_id': chat_session_id}
        )

    def __del__(self):
        try:
            self.session.close()
            self.stream_client.close()
        except:
            pass