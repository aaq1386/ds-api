"""Cloudflare bypass FastAPI."""
import argparse
import atexit
import json
import os
import re
import time
from typing import Dict
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
import uvicorn

from CloudflareBypasser import CloudflareBypasser
from DrissionPage import ChromiumPage, ChromiumOptions

try:
    from pyvirtualdisplay import Display
    HAS_DISPLAY = True
except ImportError:
    HAS_DISPLAY = False


DOCKER_MODE = os.getenv("DOCKERMODE", "false").lower() == "true"
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))
BROWSER_PATH = os.getenv("BROWSER_PATH", "/usr/bin/google-chrome")

CHROMIUM_ARGS = [
    "-no-first-run", "-force-color-profile=srgb", "-metrics-recording-only",
    "-password-store=basic", "-use-mock-keychain", "-export-tagged-pdf",
    "-no-default-browser-check", "-disable-background-mode",
    "-enable-features=NetworkService,NetworkServiceInProcess,LoadCryptoTokenExtension,PermuteTLSExtensions",
    "-disable-features=FlashDeprecationWarning,EnablePasswordsAccountStorage",
    "-deny-permission-prompts", "-disable-gpu", "-accept-lang=en-US",
]

app = FastAPI(title="CF Bypass")


class CookieResponse(BaseModel):
    cookies: Dict[str, str]
    user_agent: str


_IP_PATTERN = re.compile(
    r"^(127\\.0\\.0\\.1|localhost|0\\.0\\.0\\.0|::1|10\\.\\d+\\.\\d+\\.\\d+"
    r"|172\\.1[6-9]\\.\\d+\\.\\d+|172\\.2[0-9]\\.\\d+\\.\\d+|172\\.3[0-1]\\.\\d+\\.\\d+"
    r"|192\\.168\\.\\d+\\.\\d+)$"
)


def is_safe_url(url: str) -> bool:
    p = urlparse(url)
    if p.scheme == "file":
        return False
    if p.hostname and _IP_PATTERN.match(p.hostname):
        return False
    return True


def bypass_cloudflare(url: str, retries: int, log: bool, proxy: str = None) -> ChromiumPage:
    for load_attempt in range(3):
        options = ChromiumOptions().auto_port()
        for a in CHROMIUM_ARGS:
            options.set_argument(a)
        if DOCKER_MODE:
            options.set_argument("--no-sandbox")
            options.set_argument("--remote-debugging-port=9222")
            options.set_paths(browser_path=BROWSER_PATH).headless(False)
        else:
            options.set_paths(browser_path=BROWSER_PATH).headless(False)
        if proxy:
            options.set_proxy(proxy)
        driver = ChromiumPage(addr_or_opts=options)
        try:
            driver.get(url)
            time.sleep(5)
            try:
                body = driver.ele("tag:body", timeout=10)
                if len(body.html) < 100:
                    raise Exception("page empty")
            except Exception:
                driver.quit()
                if load_attempt < 2:
                    time.sleep(3); continue
                raise
            CloudflareBypasser(driver, retries, log).bypass()
            return driver
        except Exception as exc:
            driver.quit()
            if load_attempt < 2:
                time.sleep(3); continue
            raise exc
    raise RuntimeError("bypass failed after retries")


@app.get("/cookies", response_model=CookieResponse)
async def get_cookies(url: str, retries: int = 5, proxy: str = None):
    if not is_safe_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    try:
        d = bypass_cloudflare(url, retries, True, proxy)
        cookies = {c.get("name", ""): c.get("value", "") for c in d.cookies()}
        ua = d.user_agent
        d.quit()
        return CookieResponse(cookies=cookies, user_agent=ua)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/html")
async def get_html(url: str, retries: int = 5, proxy: str = None):
    if not is_safe_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    try:
        d = bypass_cloudflare(url, retries, True, proxy)
        html = d.html
        cj = {c.get("name", ""): c.get("value", "") for c in d.cookies()}
        resp = Response(content=html, media_type="text/html")
        resp.headers["cookies"] = json.dumps(cj)
        resp.headers["user_agent"] = d.user_agent
        d.quit()
        return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"ok": True}


def _run_server(port: int, nolog: bool, headless: bool):
    display = None
    if (headless or DOCKER_MODE) and HAS_DISPLAY:
        display = Display(visible=0, size=(1920, 1080))
        display.start()
        atexit.register(display.stop)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning" if nolog else "info")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=SERVER_PORT)
    parser.add_argument("--nolog", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    _run_server(args.port, args.nolog, args.headless)
