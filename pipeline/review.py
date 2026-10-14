from __future__ import annotations

import json
import pathlib
import re
import sys
import time

from .common import ROOT, load_json, read_jsonl, receipt, run_dir, sha


def issue(issues, artifact, severity, message, piece_id=None):
    value={"artifact":artifact,"severity":severity,"message":message}
    if piece_id: value["piece_id"]=piece_id
    issues.append(value)


def main():
    started=time.time()
    try:
        run=run_dir(sys.argv[1]); issues=[]
        required=["briefs.jsonl","articles.jsonl","video_scripts.jsonl","eligible.jsonl","decisions.jsonl"]
        for name in required:
            if not (run/name).is_file(): issue(issues,name,"error","required artifact is missing")
        if any(x["severity"]=="error" for x in issues): briefs=[]; articles=[]; scripts=[]; eligible=[]
        else:
            briefs=read_jsonl((run/"briefs.jsonl").open()); articles=read_jsonl((run/"articles.jsonl").open()); scripts=read_jsonl((run/"video_scripts.jsonl").open()); eligible=read_jsonl((run/"eligible.jsonl").open())
            if [x.get("piece_id") for x in briefs] != ["01","02","03"]: issue(issues,"briefs.jsonl","error","exactly three ordered, distinct briefs are required")
            item_versions={(x["item_id"],x["version_id"]):x for x in eligible}; used=[]
            for brief in briefs:
                piece=brief.get("piece_id")
                if not brief.get("claims"): issue(issues,"briefs.jsonl","error","brief has no claims",piece)
                pubs=set()
                for claim in brief.get("claims",[]):
                    if not claim.get("evidence"): issue(issues,"briefs.jsonl","error",f"claim {claim.get('claim_id')} has no evidence",piece)
                    for ref in claim.get("evidence",[]):
                        key=(ref.get("item_id"),ref.get("version_id")); item=item_versions.get(key)
                        if not item: issue(issues,"briefs.jsonl","error",f"unresolvable evidence {key}",piece); continue
                        pubs.add(item["publisher_id"]); used.append(item)
                        loc=ref.get("locator",{})
                        if loc.get("type")=="text":
                            content=(ROOT/item["text_path"]).read_text(encoding="utf-8",errors="replace")
                            if loc.get("quote") not in content: issue(issues,"briefs.jsonl","error","text locator does not match retained evidence",piece)
                        elif loc.get("type")=="segment":
                            segs=load_json(ROOT/item["segments_path"])
                            if loc.get("segment_id") not in {x["segment_id"] for x in segs}: issue(issues,"briefs.jsonl","error","segment locator does not resolve",piece)
                        else: issue(issues,"briefs.jsonl","error","unknown locator type",piece)
                if len(pubs)<3: issue(issues,"briefs.jsonl","error","piece uses fewer than three independent publishers",piece)
            for manifest,label,target in ((articles,"articles","article"),(scripts,"video_scripts","video script")):
                if len(manifest)!=3: issue(issues,f"{label}.jsonl","error",f"three {target}s are required")
                for row in manifest:
                    path=ROOT/row.get("path",""); piece=row.get("piece_id")
                    if not path.is_file(): issue(issues,f"{label}.jsonl","error",f"missing file {path}",piece); continue
                    text=path.read_text(encoding="utf-8"); markers=set(re.findall(r"claim:([\w-]+)",text))
                    missing=set(row.get("claim_ids",[]))-markers
                    if missing: issue(issues,row["path"],"error",f"missing claim markers: {sorted(missing)}",piece)
                    words=len(re.findall(r"\b\w+[’'-]?\w*\b",text))
                    if label=="articles" and not 600<=words<=900: issue(issues,row["path"],"warning",f"article is {words} words; target is 600–900",piece)
                    if label=="video_scripts" and not 390<=words<=800: issue(issues,row["path"],"warning",f"script is {words} words; approximate 3–5 minute target is 390–800",piece)
            kinds={x["kind"] for x in used}; pubs={x["publisher_id"] for x in used}
            if kinds != {"feed","youtube","podcast"}: issue(issues,"briefs.jsonl","error",f"series media coverage is {sorted(kinds)}; all three kinds required")
            if len(pubs)<6: issue(issues,"briefs.jsonl","error",f"series uses {len(pubs)} independent publishers; six required")
            issue(issues,"review.json","warning","Machine checks cannot establish sound interpretation; a human must inspect claims, disclosures, links, and corrections.")
        fingerprint={"as_of_date":load_json(run/"run.json")["as_of_date"],"briefs":briefs,"articles":articles,"scripts":scripts}
        for m in articles+scripts:
            path=ROOT/m["path"]
            if path.is_file(): fingerprint[m["path"]]=sha(path.read_text(encoding="utf-8"))
        result={"review_id":sha(fingerprint),"passed":not any(x["severity"]=="error" for x in issues),"issues":issues}
        print(json.dumps(result,ensure_ascii=False,indent=2)); receipt(run,"check-content","completed",started,len(briefs),1,tools=["structural-evidence-checker"])
        return 0
    except (IndexError,ValueError,KeyError,json.JSONDecodeError) as exc:
        print(exc,file=sys.stderr); return 2


if __name__=="__main__": raise SystemExit(main())
