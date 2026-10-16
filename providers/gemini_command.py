#!/usr/bin/env python3
"""JSON-in/JSON-out AI_COMMAND adapter for the Gemini Developer API free tier."""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
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


def response_schema(stage: str) -> dict | None:
    if stage != "create_briefs":
        return None
    locator = {"type": "object", "properties": {
        "version_id": {"type": "string"}, "item_id": {"type": "string"},
        "source_id": {"type": "string"}, "publisher_id": {"type": "string"},
        "quote": {"type": "string"}, "segment_id": {"type": "string"}},
        "required": ["version_id", "item_id", "source_id", "publisher_id"]}
    claim = {"type": "object", "properties": {
        "statement": {"type": "string"},
        "claim_type": {"type": "string", "enum": ["reported_fact", "source_claim", "inference"]},
        "evidence_locators": {"type": "array", "items": locator, "minItems": 1}},
        "required": ["statement", "claim_type", "evidence_locators"]}
    brief = {"type": "object", "properties": {
        "piece_id": {"type": "string", "enum": ["01", "02", "03"]},
        "title": {"type": "string"}, "question": {"type": "string"},
        "argument": {"type": "string"}, "synthesis": {"type": "string"},
        "limitations": {"type": "string"},
        "claims": {"type": "array", "items": claim, "minItems": 3}},
        "required": ["piece_id", "title", "question", "argument", "synthesis", "limitations", "claims"]}
    return {"type": "array", "items": brief, "minItems": 3, "maxItems": 3}


def main() -> int:
    key = env_value("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not configured", file=sys.stderr)
        return 2
    try:
        request_data = json.load(sys.stdin)
        stage = request_data["stage"]
        model = os.environ.get("GEMINI_MODEL") or env_value("GEMINI_MODEL") or "gemini-flash-lite-latest"
        instruction = (
            "You are one component in an evidence-traceable editorial pipeline. Follow the task instructions exactly. "
            "Never invent a source, passage, timestamp, identifier, or claim. Return only " + expected_shape(stage) +
            "; do not use Markdown fences around the JSON.\n\nTASK INSTRUCTIONS:\n" + request_data["prompt"] +
            "\n\nSTRUCTURED INPUT:\n" + json.dumps(request_data["input"], ensure_ascii=False)
        )
        if stage == "create_briefs":
            instruction += ("\n\nSTRICT BRIEF CONTRACT: Each brief must cite at least three distinct publisher_id values. "
                            "Use exactly three claims per brief and use a different publisher_id for each claim. "
                            "Copy item_id, version_id, source_id, and publisher_id exactly from the structured input. "
                            "For text, copy an exact quote; for media, copy an existing segment_id. Never reuse one "
                            "publisher for two claims in the same brief.")
        generation_config = {"responseMimeType": "application/json", "temperature": 0.2}
        schema = response_schema(stage)
        if schema is not None: generation_config["responseJsonSchema"] = schema
        body = {"contents": [{"role": "user", "parts": [{"text": instruction}]}],
                "generationConfig": generation_config}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        payload = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=180) as response:
                    payload = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 3: raise
                retry_after = exc.headers.get("Retry-After")
                try: delay = min(15.0, max(1.0, float(retry_after)))
                except (TypeError, ValueError): delay = float(2 ** (attempt + 1))
                time.sleep(delay)
        if payload is None: raise RuntimeError("Gemini API returned no response")
        text = "".join(part.get("text", "") for part in payload["candidates"][0]["content"]["parts"])
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        result = json.loads(text)
        if isinstance(result, dict):
            wrapper = {"select_items": "decisions", "create_briefs": "briefs",
                       "write_articles": "articles", "write_scripts": "scripts"}.get(stage)
            if wrapper and isinstance(result.get(wrapper), list): result = result[wrapper]
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
