#!/usr/bin/env python3
"""JSON-in/JSON-out AI_COMMAND adapter for the Gemini Developer API free tier."""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]


def env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    path = ROOT / ".env.local"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def expected_shape(stage: str) -> str:
    return {
        "select_items": "a JSON array containing exactly one decision object per input item",
        "create_briefs": "a JSON array containing exactly three brief objects in piece order 01, 02, 03",
        "write_articles": "a JSON array in brief order; each object must contain a markdown string field named markdown",
        "write_scripts": "a JSON array in brief order; each object must contain a markdown string field named markdown",
    }.get(stage, "valid JSON")


def main() -> int:
    key = env_value("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not configured", file=sys.stderr)
        return 2
    try:
        request_data = json.load(sys.stdin)
        stage = request_data["stage"]
        model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
        instruction = (
            "You are one component in an evidence-traceable editorial pipeline. Follow the task instructions exactly. "
            "Never invent a source, passage, timestamp, identifier, or claim. Return only " + expected_shape(stage) +
            "; do not use Markdown fences around the JSON.\n\nTASK INSTRUCTIONS:\n" + request_data["prompt"] +
            "\n\nSTRUCTURED INPUT:\n" + json.dumps(request_data["input"], ensure_ascii=False)
        )
        body = {"contents": [{"role": "user", "parts": [{"text": instruction}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=180) as response:
            payload = json.load(response)
        text = "".join(part.get("text", "") for part in payload["candidates"][0]["content"]["parts"])
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        result = json.loads(text)
        json.dump(result, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    except urllib.error.HTTPError as exc:
        # Do not echo response bodies: provider errors can contain request details.
        print(f"Gemini API returned HTTP {exc.code}", file=sys.stderr)
        return 1
    except (KeyError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        print(f"Gemini provider error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
