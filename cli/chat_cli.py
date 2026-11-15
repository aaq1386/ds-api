import argparse
import json
import sys
import requests

DEFAULT_BASE = "http://127.0.0.1:8787"


def new_conversation(base, title="CLI chat"):
    r = requests.post(f"{base}/api/conversations", json={"title": title}, timeout=10)
    r.raise_for_status()
    return r.json()["id"]


def stream_chat(base, conv_id, prompt, thinking):
    payload = {"conversation_id": conv_id, "prompt": prompt,
               "thinking": thinking, "search": False}
    with requests.post(f"{base}/api/chat/stream", json=payload, stream=True, timeout=None) as r:
        r.raise_for_status()
        evt = None
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("event:"):
                evt = raw[6:].strip()
                continue
            if not raw.startswith("data:"):
                continue
            try:
                data = json.loads(raw[5:].strip())
            except json.JSONDecodeError:
                continue
            if evt == "text":
                print(data["content"], end="", flush=True)
            elif evt == "thinking":
                print(f"\n[thinking] {data['content']}", end="", flush=True)
            elif evt == "error":
                print(f"\nERROR: {data['message']}", file=sys.stderr)
            elif evt == "done":
                print()
                return


def main():
    p = argparse.ArgumentParser()
    p.add_argument("prompt")
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--thinking", action="store_true", default=True)
    p.add_argument("--no-thinking", dest="thinking", action="store_false")
    args = p.parse_args()
    conv_id = new_conversation(args.base)
    print(f"conversation: {conv_id}")
    stream_chat(args.base, conv_id, args.prompt, args.thinking)


if __name__ == "__main__":
    main()
