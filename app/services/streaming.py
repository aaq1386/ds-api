import json
from typing import Any


def sse_event(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    lines = payload.split("\n")
    data_lines = "\n".join(f"data: {ln}" for ln in lines)
    return f"event: {event}\n{data_lines}\n\n"
