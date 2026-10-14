from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from typing import Any, Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: pathlib.Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def read_jsonl(stream: Iterable[str]) -> list[dict[str, Any]]:
    out = []
    for line_no, line in enumerate(stream, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_no}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONL line {line_no} is not an object")
        out.append(value)
    return out


def write_jsonl(records: Iterable[dict[str, Any]], stream=sys.stdout) -> int:
    count = 0
    for record in records:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        count += 1
    return count


def sha(value: Any) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def repo_path(path: pathlib.Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def run_dir(arg: str) -> pathlib.Path:
    p = pathlib.Path(arg)
    if not p.is_absolute():
        p = ROOT / p
    if not (p / "run.json").is_file():
        raise ValueError(f"not a run directory: {arg}")
    return p.resolve()


def receipt(run: pathlib.Path, stage: str, status: str, started: float, input_count: int | None,
            output_count: int | None, errors: list[str] | None = None, tools: list[str] | None = None,
            cost_usd: float | None = 0.0, cost_estimated: bool = False) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    payload = {
        "stage": stage, "status": status, "input_count": input_count, "output_count": output_count,
        "started_at": dt.datetime.fromtimestamp(started, dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "finished_at": now(), "elapsed_seconds": round(time.time() - started, 3),
        "tools_or_models": tools or ["python-standard-library"], "cost_usd": cost_usd,
        "cost_estimated": cost_estimated, "errors": errors or [],
    }
    dump_json(run / "logs" / f"{stage}-{stamp}.json", payload)


def fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "MIT-1.125-PS04/1.0 (+educational research)"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def clean_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|nav|footer|svg).*?>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h[1-6]>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    lines = [re.sub(r"\s+", " ", x).strip() for x in raw.splitlines()]
    return "\n".join(x for x in lines if x)


def model_json(stage: str, prompt: str, payload: Any) -> Any | None:
    """Invoke a user-configured JSON-in/JSON-out model command, or return None."""
    command = os.environ.get("AI_COMMAND")
    if not command:
        return None
    request = {"stage": stage, "prompt": prompt, "input": payload}
    proc = subprocess.run(shlex.split(command), input=json.dumps(request), text=True, capture_output=True)
    if proc.returncode:
        raise RuntimeError(f"AI_COMMAND failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def require_fields(obj: dict[str, Any], fields: list[str], label: str) -> None:
    missing = [f for f in fields if f not in obj]
    if missing:
        raise ValueError(f"{label} missing fields: {', '.join(missing)}")


def first_sentences(text: str, limit: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text).strip())
    return " ".join(parts[:limit])[:700]
