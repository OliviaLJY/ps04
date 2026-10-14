from __future__ import annotations

import json
import os
import pathlib
import sys
import time

from .common import ROOT, dump_json, load_json, now, read_jsonl, receipt, run_dir, write_jsonl

STORE = pathlib.Path(os.environ.get("EVIDENCE_DIR", str(ROOT / "data" / "evidence"))).resolve()
INDEX = STORE / "index.json"


def init():
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / "versions").mkdir(exist_ok=True)
    if not INDEX.exists():
        dump_json(INDEX, {"schema_version": 1, "items": {}})


def upsert(arg):
    started = time.time(); run = run_dir(arg); init(); index = load_json(INDEX)
    records = read_jsonl(sys.stdin); changes = []
    for record in records:
        item_id, version_id = record["item_id"], record["version_id"]
        entry = index["items"].get(item_id)
        if entry is None:
            change = "new"; entry = {"latest": version_id, "versions": [], "runs": []}
            index["items"][item_id] = entry
        elif version_id in entry["versions"]:
            change = "unchanged"
        else:
            change = "changed"
        version_file = STORE / "versions" / f"{version_id}.json"
        if not version_file.exists():
            dump_json(version_file, record)
        if version_id not in entry["versions"]:
            entry["versions"].append(version_id)
        entry["latest"] = version_id
        run_id = load_json(run / "run.json")["run_id"]
        observation = {"run_id": run_id, "version_id": version_id, "observed_at": now()}
        if not any(x["run_id"] == run_id and x["version_id"] == version_id for x in entry["runs"]):
            entry["runs"].append(observation)
        changes.append({"item_id": item_id, "version_id": version_id, "change": change})
    dump_json(INDEX, index); write_jsonl(changes)
    receipt(run, "store-upsert", "completed", started, len(records), len(changes), tools=["json-version-store"])


def list_items():
    init(); index = load_json(INDEX)
    for item_id in sorted(index["items"]):
        path = STORE / "versions" / f"{index['items'][item_id]['latest']}.json"
        print(json.dumps(load_json(path), ensure_ascii=False, separators=(",", ":")))


def get(item_id, version_id=None):
    init(); index = load_json(INDEX); entry = index["items"].get(item_id)
    if not entry:
        print(f"item not found: {item_id}", file=sys.stderr); return 1
    version_id = version_id or entry["latest"]
    if version_id not in entry["versions"]:
        print(f"version not found: {item_id} {version_id}", file=sys.stderr); return 1
    print(json.dumps(load_json(STORE / "versions" / f"{version_id}.json"), ensure_ascii=False, separators=(",", ":")))
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("init", "upsert", "list", "get"):
        print("usage: store.sh {init|upsert RUN_DIR|list|get ITEM_ID [VERSION_ID]}", file=sys.stderr); return 2
    command = sys.argv[1]
    try:
        if command == "init": init(); return 0
        if command == "list": list_items(); return 0
        if command == "upsert" and len(sys.argv) == 3: upsert(sys.argv[2]); return 0
        if command == "get" and len(sys.argv) in (3, 4): return get(sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else None)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr); return 2
    print("invalid arguments", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
