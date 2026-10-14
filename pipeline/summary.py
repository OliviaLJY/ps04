from __future__ import annotations

import json
import pathlib
import sys

from .common import load_json, read_jsonl, run_dir


def lines(path):
    return read_jsonl(path.open(encoding="utf-8")) if path.is_file() else None


def count_where(records,key,value):
    return None if records is None else sum(1 for x in records if x.get(key)==value)


def main():
    try:
        run=run_dir(sys.argv[1]); meta=load_json(run/"run.json")
        candidates=lines(run/"candidates.jsonl"); items=lines(run/"items.jsonl"); changes=lines(run/"changes.jsonl")
        eligible=lines(run/"eligible.jsonl"); exclusions=lines(run/"exclusions.jsonl"); decisions=lines(run/"decisions.jsonl")
        articles=lines(run/"articles.jsonl"); scripts=lines(run/"video_scripts.jsonl")
        receipts=[]
        for path in sorted((run/"logs").glob("*.json")):
            try: receipts.append(load_json(path))
            except Exception: pass
        failed=[{"stage":x.get("stage"),"status":x.get("status"),"errors":x.get("errors",[])} for x in receipts if x.get("status") not in ("completed",)]
        review=load_json(run/"review.json") if (run/"review.json").is_file() else None
        approval=load_json(run/"approval.json") if (run/"approval.json").is_file() else None
        ready=bool(review and review.get("passed") and approval and approval.get("decision")=="approve" and approval.get("review_id")==review.get("review_id") and (run/"package/manifest.json").is_file())
        if ready: status="ready_for_production"
        elif articles and scripts and review and review.get("passed"): status="awaiting_review"
        else: status="failed"
        pubs={x.get("publisher_id") for x in (eligible or [])}; kinds={k:len({x["item_id"] for x in (eligible or []) if x.get("kind")==k}) for k in ("feed","youtube","podcast")}
        raw=len(candidates) if candidates is not None else None; distinct=len({x["item_id"] for x in candidates}) if candidates is not None else None
        known_costs=[x["cost_usd"] for x in receipts if isinstance(x.get("cost_usd"),(int,float))]
        unknown=[x.get("stage") for x in receipts if x.get("cost_usd") is None]
        summary={"run_id":meta["run_id"],"status":status,"counts":{"discovered":raw,"distinct_discovered":distinct,"duplicate_observations":None if raw is None else raw-distinct,
                  "extracted":None if items is None else len(items),"new":count_where(changes,"change","new"),"changed":count_where(changes,"change","changed"),"unchanged":count_where(changes,"change","unchanged"),
                  "eligible":None if eligible is None else len(eligible),"excluded":None if exclusions is None else len(exclusions),"accepted":count_where(decisions,"decision","accept"),"rejected":count_where(decisions,"decision","reject"),"deferred":count_where(decisions,"decision","defer"),
                  "articles":None if articles is None else len(articles),"video_scripts":None if scripts is None else len(scripts)},
                 "coverage":{"by_kind":kinds,"independent_publishers":len(pubs)},"failed_or_incomplete_stages":failed,
                 "elapsed_seconds":round(sum(float(x.get("elapsed_seconds",0)) for x in receipts),3),
                 "tools_or_models":sorted({tool for x in receipts for tool in x.get("tools_or_models",[])}),
                 "cost":{"known_or_estimated_usd":round(sum(known_costs),4),"unknown_stage_costs":unknown},
                 "remaining_manual_actions":["Inspect at least three accepted and three rejected/deferred decisions.","Revise policy and preserve the comparison run.","Create matching human approval.json after corrections.","Render in Google Vids or HeyGen, publish on Substack/YouTube, and verify links.","Record the separate technical demonstration."],
                 "publication_links":load_json(run/"package/publication_links.json") if (run/"package/publication_links.json").is_file() else []}
        print(json.dumps(summary,ensure_ascii=False,indent=2)); return 0
    except (IndexError,ValueError,KeyError,json.JSONDecodeError) as exc:
        print(exc,file=sys.stderr); return 2


if __name__=="__main__": raise SystemExit(main())
