from __future__ import annotations

import json
import os
import re
import sys
import time

from .common import ROOT, load_json, model_json, read_jsonl, receipt, repo_path, run_dir, write_jsonl


def source_note(ref, items):
    item = items[ref["item_id"]]
    loc = ref["locator"]
    if loc["type"] == "segment":
        segments = load_json(ROOT / item["segments_path"]); seg = next(x for x in segments if x["segment_id"] == loc["segment_id"])
        locator = f"{int(seg['start_seconds']//60)}:{int(seg['start_seconds']%60):02d}"
    else:
        locator = f'“{loc["quote"][:120]}”'
    return f"[{item['title']}]({item['url']}) — {item['publisher_id']}, {item['published_at'][:10] if item.get('published_at') else 'undated'}, {locator}"


def article_text(brief, project, items):
    claims = brief["claims"]; refs = []
    for c in claims:
        for e in c["evidence"]:
            if (e["item_id"], e["version_id"]) not in [(x["item_id"], x["version_id"]) for x in refs]: refs.append(e)
    evidence_paras = []
    for i, claim in enumerate(claims, 1):
        evidence_paras.append(f"## {['The observable change','What the evidence supports','The practical reading','What remains uncertain'][min(i-1,3)]}\n\n"
                              f"<!-- claim:{claim['claim_id']} -->\n{claim['statement']} This matters because the claim is only as useful as the decision it changes. The supporting record is specific and inspectable; it should not be generalized beyond the source’s setting. "
                              f"For {project['audience']}, the appropriate response is to treat this as {('a reported observation' if claim['type'] != 'inference' else 'a cross-source interpretation')}, not as a universal result.\n\n"
                              "Ask what was measured, what baseline was used, and which deployment conditions were omitted. Those answers determine whether a team should experiment, procure, or wait.")
    refs_md = "\n".join(f"{i}. {source_note(x, items)}" for i, x in enumerate(refs, 1))
    return (f"# {brief['title']}\n\n*As of {load_json(ROOT / 'runs' / '__placeholder__' / 'run.json')['as_of_date'] if False else '{{AS_OF}}'}*\n\n"
            f"{brief['argument']} This edition of **{project['publication_name']}** examines the question for {project['audience']}. The goal is not to rank announcements; it is to identify which observations deserve to change a decision now.\n\n"
            + "\n\n".join(evidence_paras) +
            f"\n\n## Counterargument and limit\n\n{brief['limitations']} A plausible counterargument is that rapid product iteration makes a short evidence window more representative than older evaluations. That is partly right, but freshness cannot substitute for controls, comparison groups, or post-deployment observation. The responsible conclusion is therefore directional and revisable.\n\n"
            f"## What to do next\n\nTest the weak link in this argument. Record the baseline task, review burden, failure modes, and total time—not just generated output. Revisit the decision when independent evidence covers those measures.\n\n"
            f"## Sources\n\n{refs_md}\n\n*Draft prepared with AI-assisted synthesis and requires human editorial approval before publication.*\n")


def script_text(brief, project, items):
    claims = brief["claims"]; refs=[]
    for c in claims:
        for e in c["evidence"]:
            if e["item_id"] not in [x["item_id"] for x in refs]: refs.append(e)
    scenes=[]
    for i, c in enumerate(claims, 1):
        scenes.append(f"### Scene {i} — Evidence\n\n**Visual:** Show the source title and a label: `{c['type']}`.\n\n**Narration:** <!-- claim:{c['claim_id']} --> {c['statement']} The key is not the headline alone. Ask what the source observed, what it did not measure, and whether that matches your operating conditions. This is evidence for a bounded decision, not permission to assume the same outcome everywhere.")
    notes="\n".join(f"- {source_note(x, items)}" for x in refs)
    return f"# {brief['title']} — Video Script\n\n**Target length:** 3–5 minutes  \n**AI disclosure:** AI-assisted draft; human review required.\n\n### Opening\n\n**Visual:** {project['publication_name']} title card and the question “{brief['question']}”\n\n**Narration:** A new claim can be real and still be insufficient for your next decision. Here is what changed, what the evidence actually supports, and what to watch before you act.\n\n" + "\n\n".join(scenes) + f"\n\n### Close\n\n**Visual:** Three-item checklist: baseline, review burden, failure modes.\n\n**Narration:** {brief['argument']} Treat this as a testable view. Capture your baseline, run a bounded trial, and come back when the missing evidence arrives.\n\n## Description source notes\n\n{notes}\n\n**Production handoff:** Render in Google Vids or HeyGen; add on-screen citations and the final Substack URL before upload.\n"


def main():
    if len(sys.argv)!=3 or sys.argv[1] not in ("articles","scripts"):
        print("usage: generate.py {articles|scripts} RUN_DIR", file=sys.stderr); return 2
    kind=sys.argv[1]; started=time.time()
    try:
        run=run_dir(sys.argv[2]); briefs=read_jsonl(sys.stdin); project=load_json(run/"config"/"project.json")
        items={x["item_id"]:x for x in read_jsonl((run/"eligible.jsonl").open(encoding="utf-8"))}
        prompt=(run/"prompts"/("write_articles.md" if kind=="articles" else "write_video_scripts.md")).read_text(encoding="utf-8")
        modeled=model_json(f"write_{kind}",prompt,{"briefs":briefs,"project":project})
        outdir=run/("articles" if kind=="articles" else "video_scripts"); outdir.mkdir(exist_ok=True)
        manifests=[]
        for i, brief in enumerate(briefs):
            piece=brief["piece_id"]
            if modeled is not None:
                text=modeled[i]["markdown"]
            else:
                text=article_text(brief,project,items) if kind=="articles" else script_text(brief,project,items)
            text=text.replace("{AS_OF}",load_json(run/"run.json")["as_of_date"])
            path=outdir/f"{piece}.md"; path.write_text(text,encoding="utf-8")
            manifests.append({"piece_id":piece,"path":repo_path(path),"claim_ids":[x["claim_id"] for x in brief["claims"]]})
        write_jsonl(manifests); tools=[os.environ.get("AI_MODEL_NAME", "AI_COMMAND")] if modeled is not None else ["deterministic-draft-fallback (set AI_COMMAND for submitted live runs)"]
        receipt(run,f"write-{kind}","completed",started,len(briefs),len(manifests),tools=tools,cost_usd=None if modeled is not None else 0.0)
        return 0
    except (ValueError,KeyError,IndexError) as exc:
        print(exc,file=sys.stderr); return 2


if __name__=="__main__": raise SystemExit(main())
