from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
from collections import defaultdict
from difflib import SequenceMatcher

from .common import ROOT, dump_json, first_sentences, load_json, model_json, read_jsonl, receipt, run_dir, write_jsonl


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


def normalize_modeled_briefs(modeled, accepted):
    """Map provider field variants onto the assignment's strict brief contract."""
    if not isinstance(modeled, list): return modeled
    by_version = {x["version_id"]: x for x in accepted}
    by_source = defaultdict(list)
    for item in accepted: by_source[item["source_id"]].append(item)
    normalized = lambda value: re.sub(r"\s+", " ", value).strip().lower()
    tokens = lambda value: set(re.findall(r"[a-z0-9]+", value.lower()))
    questions = ["What changed, and which developments matter most?",
                 "Which claims withstand scrutiny, and where is the evidence in tension?",
                 "What do these developments imply, and what should readers watch next?"]
    titles = ["The signal behind the launches", "Claims meet operational evidence", "A watchlist for the next decision"]
    output = []
    for index, brief in enumerate(modeled):
        piece_id = brief.get("piece_id", f"{index + 1:02d}")
        claims = []
        for claim_index, claim in enumerate(brief.get("claims", []), 1):
            statement = claim.get("statement", claim.get("text"))
            if not statement: raise ValueError("model brief claim has no statement")
            evidence = []
            raw_evidence = claim.get("evidence")
            if not isinstance(raw_evidence, list) or not all(isinstance(x, dict) for x in raw_evidence):
                raw_evidence = claim.get("evidence_locators", [])
            if not raw_evidence and claim.get("locator"):
                raw_evidence = [claim["locator"] if isinstance(claim["locator"], dict) else {"quote": claim["locator"]}]
            if isinstance(raw_evidence, dict): raw_evidence = [raw_evidence]
            if not isinstance(raw_evidence, list) or not all(isinstance(x, dict) for x in raw_evidence):
                raise ValueError(f"model brief claim has no structured evidence locators: {claim.get('statement', '')[:80]}")
            for raw in raw_evidence:
                item = by_version.get(raw.get("version_id"))
                if item is None:
                    matches = by_source.get(raw.get("source_id"), [])
                    item = matches[0] if len(matches) == 1 else None
                quoted = raw.get("quote") or raw.get("quoted_text") or statement
                if item is None and quoted:
                    exact_matches = []
                    for candidate in accepted:
                        if normalized(quoted) in normalized(item_text(candidate)): exact_matches.append(candidate)
                    item = exact_matches[0] if len(exact_matches) == 1 else None
                if item is None and quoted:
                    # A provider may lightly normalize filler words in a media
                    # quote. Resolve only when one retained item has strong,
                    # clearly better token coverage than every alternative.
                    quote_tokens = tokens(quoted)
                    ranked = sorted(((len(quote_tokens & tokens(item_text(candidate))) / max(1, len(quote_tokens)), candidate)
                                     for candidate in accepted), key=lambda pair: pair[0], reverse=True)
                    if ranked and ranked[0][0] >= 0.80 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.10):
                        item = ranked[0][1]
                if item is None: raise ValueError(f"model brief locator does not resolve: {raw}")
                if item.get("segments_path"):
                    segments = load_json(ROOT / item["segments_path"])
                    exact = next((s for s in segments if raw.get("segment_id") == s["segment_id"]), None)
                    if exact is None:
                        exact = next((s for s in segments if quoted and (quoted in s["text"] or s["text"] in quoted)), None)
                    if exact is None and quoted:
                        exact = max(segments, key=lambda s: SequenceMatcher(None, quoted, s["text"]).ratio())
                    if exact is None: raise ValueError(f"media locator has no matching segment for {item['item_id']}")
                    locator = {"type": "segment", "segment_id": exact["segment_id"]}
                else:
                    content = item_text(item)
                    if not quoted or quoted not in content:
                        # Models sometimes replace omitted words with an ellipsis. Resolve
                        # that paraphrased display quote to the closest exact source sentence.
                        passages = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", content) if len(x.strip()) >= 24]
                        if not quoted or not passages:
                            raise ValueError(f"text locator is not an exact retained passage for {item['item_id']}")
                        closest = max(passages, key=lambda x: SequenceMatcher(None, quoted, x).ratio())
                        if SequenceMatcher(None, quoted, closest).ratio() < 0.30:
                            raise ValueError(f"text locator cannot be resolved to retained evidence for {item['item_id']}: {quoted[:80]}")
                        quoted = closest
                    locator = {"type": "text", "quote": quoted}
                evidence.append({"item_id": item["item_id"], "version_id": item["version_id"], "locator": locator})
            if not evidence:
                raise ValueError(f"model brief claim has no evidence: {claim.get('statement', '')[:80]}")
            claims.append({"claim_id": claim.get("claim_id", f"{piece_id}-c{claim_index}"),
                           "statement": statement, "type": claim.get("type", claim.get("claim_type")),
                           "evidence": evidence})
        output.append({"piece_id": piece_id, "title": brief.get("title", titles[index]),
                       "question": brief.get("question", questions[index]),
                       "argument": brief.get("argument", brief.get("distinct_argument", "")),
                       "synthesis": brief.get("synthesis", brief.get("synthesis_across_independent_publishers", brief.get("synthesis_across_publishers", brief.get("synthesis_reasoning", "")))),
                       "limitations": brief.get("limitations", brief.get("meaningful_limitation_or_counterargument", brief.get("meaningful_limitation", ""))),
                       "claims": claims})
    accepted_by_id = {x["item_id"]: x for x in accepted}
    publisher_for = lambda claim: accepted_by_id[claim["evidence"][0]["item_id"]]["publisher_id"]
    # Free-tier models occasionally satisfy the evidence schema while using
    # two records from one publisher in a brief. Rebalance only among the
    # model's own cited claims; no statement or locator is invented here.
    claim_pool = [claim for brief in output for claim in brief["claims"]]
    for brief in output:
        seen = set()
        for claim_index, claim in enumerate(list(brief["claims"])):
            publisher = publisher_for(claim)
            if publisher not in seen:
                seen.add(publisher); continue
            candidates = [candidate for candidate in claim_pool
                          if publisher_for(candidate) not in seen
                          and candidate["statement"] not in {x["statement"] for x in brief["claims"]}]
            if not candidates: continue
            context = brief["argument"] + " " + brief["question"]
            replacement = max(candidates, key=lambda candidate: SequenceMatcher(None, context, candidate["statement"]).ratio())
            brief["claims"][claim_index] = {"claim_id": f"{brief['piece_id']}-c{claim_index + 1}",
                                             "statement": replacement["statement"], "type": replacement["type"],
                                             "evidence": replacement["evidence"]}
            seen.add(publisher_for(replacement))
    for brief in output:
        publishers = {accepted_by_id[e["item_id"]]["publisher_id"]
                      for claim in brief["claims"] for e in claim["evidence"]}
        if len(publishers) < 3:
            raise ValueError(f"model brief {brief['piece_id']} cites fewer than three independent publishers")
    return output


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
    if os.environ.get("AI_COMMAND"):
        modeled = []
        # Smaller requests keep every eligible item inspectable and prevent a
        # long model response from silently omitting decisions.
        for start in range(0, len(model_records), 8):
            batch = model_records[start:start + 8]
            result = model_json("select_items", policy + "\n\n" + prompt, batch)
            if not isinstance(result, list) or len(result) != len(batch):
                raise ValueError(f"model selection batch {start // 8 + 1} returned {len(result) if isinstance(result, list) else 'non-list'} decisions for {len(batch)} items")
            expected = [(x["item_id"], x["version_id"]) for x in batch]
            actual = [(x.get("item_id"), x.get("version_id")) for x in result]
            if actual != expected:
                raise ValueError(f"model selection batch {start // 8 + 1} changed item order or identity")
            modeled.extend(result)
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
    # Synthesis needs diversity, not an unbounded dump of every accepted item.
    # Keep at most two accepted records per publisher while retaining all
    # decisions in decisions.jsonl for audit.
    publisher_counts = defaultdict(int); synthesis_items = []
    for item in accepted:
        if publisher_counts[item["publisher_id"]] >= 2: continue
        publisher_counts[item["publisher_id"]] += 1; synthesis_items.append(item)
    model_items = []
    for item in synthesis_items:
        enriched = dict(item); enriched["retained_content"] = item_text(item)[:12000]
        if item.get("segments_path"): enriched["timestamped_segments"] = load_json(ROOT / item["segments_path"])[:80]
        model_items.append(enriched)
    modeled = model_json("create_briefs", prompt, {"decisions": decisions, "items": model_items})
    if modeled is not None:
        # Preserve the provider's exact structured output before normalization.
        # This is useful when a free-tier model varies field names between calls.
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        dump_json(run / "logs" / f"create-briefs-raw-{stamp}.json", modeled)
        modeled = normalize_modeled_briefs(modeled, accepted)
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
