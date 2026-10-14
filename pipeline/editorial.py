from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
from collections import defaultdict

from .common import ROOT, first_sentences, load_json, model_json, read_jsonl, receipt, run_dir, write_jsonl


def item_text(item):
    return (ROOT / item["text_path"]).read_text(encoding="utf-8", errors="replace")


def evidence_ref(item):
    if item.get("segments_path"):
        segments = load_json(ROOT / item["segments_path"])
        if not segments:
            raise ValueError(f"empty segment file for {item['item_id']}")
        locator = {"type": "segment", "segment_id": segments[0]["segment_id"]}
    else:
        source = item_text(item)
        # Locators must be byte-for-byte passages, not normalized paraphrases.
        quote = source.strip()[:500]
        locator = {"type": "text", "quote": quote}
    return {"item_id": item["item_id"], "version_id": item["version_id"], "locator": locator}


def select(run, records):
    prompt = (run / "prompts" / "select_items.md").read_text(encoding="utf-8")
    policy = (run / "config" / "editorial_policy.md").read_text(encoding="utf-8")
    model_records = []
    for item in records:
        enriched = dict(item)
        enriched["retained_content"] = item_text(item)[:12000]
        if item.get("segments_path"):
            enriched["timestamped_segments"] = load_json(ROOT / item["segments_path"])[:80]
        model_records.append(enriched)
    modeled = model_json("select_items", policy + "\n\n" + prompt, model_records)
    if modeled is not None:
        if not isinstance(modeled, list) or len(modeled) != len(records):
            raise ValueError("model selection must return one decision per eligible item")
        return modeled, [os.environ.get("AI_MODEL_NAME", "AI_COMMAND")]
    # Inspectable fallback for local tests; live submitted runs should set AI_COMMAND.
    by_publisher = defaultdict(int); out = []
    for i, item in enumerate(records):
        text = item_text(item)
        commercial = bool(re.search(r"\b(sponsored|affiliate|buy now|limited offer)\b", text, re.I))
        if len(text.split()) < 45:
            decision, reason = "defer", "Substantive content is too short to assess the claim and its evidence."
            pieces = []
        elif commercial and not re.search(r"\b(method|data|study|benchmark|limitation)\b", text, re.I):
            decision, reason = "reject", "Commercial framing is not supported by inspectable methods or independent evidence."
            pieces = []
        elif by_publisher[item["publisher_id"]] >= 2:
            decision, reason = "defer", "Held to prevent one publisher from dominating the evidence mix."
            pieces = []
        else:
            decision = "accept"; by_publisher[item["publisher_id"]] += 1
            pieces = [f"{(i % 3) + 1:02d}"]
            reason = "Fresh, substantive evidence with an attributable passage; accepted subject to claim-level verification."
        out.append({"item_id": item["item_id"], "version_id": item["version_id"],
                    "decision": decision, "reason": reason, "piece_ids": pieces})
    return out, ["deterministic-editorial-fallback (set AI_COMMAND for submitted live runs)"]


def create_briefs(run, decisions):
    items = {x["item_id"]: x for x in read_jsonl((run / "eligible.jsonl").open(encoding="utf-8"))}
    accepted = [items[x["item_id"]] for x in decisions if x.get("decision") == "accept" and x["item_id"] in items]
    publishers = {x["publisher_id"] for x in accepted}
    kinds = {x["kind"] for x in accepted}
    if len(accepted) < 6 or len(publishers) < 3 or kinds != {"feed", "youtube", "podcast"}:
        raise RuntimeError("insufficient accepted evidence: need >=6 items, >=3 publishers, and all three media kinds")
    prompt = (run / "prompts" / "create_briefs.md").read_text(encoding="utf-8")
    model_items = []
    for item in accepted:
        enriched = dict(item); enriched["retained_content"] = item_text(item)[:12000]
        if item.get("segments_path"): enriched["timestamped_segments"] = load_json(ROOT / item["segments_path"])[:80]
        model_items.append(enriched)
    modeled = model_json("create_briefs", prompt, {"decisions": decisions, "items": model_items})
    if modeled is not None:
        if not isinstance(modeled, list) or [x.get("piece_id") for x in modeled] != ["01", "02", "03"]:
            raise ValueError("model must return briefs 01, 02, 03")
        return modeled, [os.environ.get("AI_MODEL_NAME", "AI_COMMAND")]
    project = load_json(run / "config" / "project.json")
    questions = [
        "What changed, and which developments matter most?",
        "Which claims withstand scrutiny, and where is the evidence in tension?",
        "What do these developments imply, and what should readers watch next?",
    ]
    groups = [[], [], []]
    for i, item in enumerate(accepted): groups[i % 3].append(item)
    # Ensure every piece gets three publisher perspectives by borrowing evidence when needed.
    for group in groups:
        for item in accepted:
            if len({x["publisher_id"] for x in group}) >= 3: break
            if item["publisher_id"] not in {x["publisher_id"] for x in group}: group.append(item)
    briefs = []
    for idx, group in enumerate(groups):
        piece_id = f"{idx+1:02d}"; chosen = group[:4]
        claims = []
        for j, item in enumerate(chosen[:3], 1):
            excerpt = first_sentences(item_text(item), 1)
            claims.append({"claim_id": f"{piece_id}-c{j}", "statement": excerpt[:300],
                           "type": "source_claim", "evidence": [evidence_ref(item)]})
        claims.append({"claim_id": f"{piece_id}-c4",
                       "statement": f"Taken together, these sources suggest that {project['central_question'].rstrip('?').lower()} requires separating demonstrated capability from operational evidence.",
                       "type": "inference", "evidence": [evidence_ref(x) for x in chosen[:3]]})
        briefs.append({"piece_id": piece_id,
                       "title": ["The signal behind the launches", "Claims meet operational evidence", "A watchlist for the next decision"][idx],
                       "question": questions[idx],
                       "argument": claims[-1]["statement"],
                       "synthesis": "The sources describe different layers of the same decision: announced capability, observed use, and operational constraint. Comparing them prevents a product claim from standing in for deployment evidence.",
                       "limitations": "The evidence window is short, vendor reporting is selective, and the source set does not establish long-run causal effects.",
                       "claims": claims})
    return briefs, ["deterministic-brief-fallback (set AI_COMMAND for submitted live runs)"]


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("select", "briefs"):
        print("usage: editorial.py {select|briefs} RUN_DIR", file=sys.stderr); return 2
    stage = "select-items" if sys.argv[1] == "select" else "create-briefs"
    started = time.time()
    try:
        run = run_dir(sys.argv[2]); records = read_jsonl(sys.stdin)
        output, tools = select(run, records) if sys.argv[1] == "select" else create_briefs(run, records)
        write_jsonl(output); receipt(run, stage, "completed", started, len(records), len(output), tools=tools,
                                    cost_usd=None if os.environ.get("AI_COMMAND") else 0.0)
        return 0
    except RuntimeError as exc:
        print(exc, file=sys.stderr); receipt(run, stage, "failed", started, len(records), 0, [str(exc)]); return 1
    except (ValueError, KeyError, IndexError) as exc:
        print(exc, file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
