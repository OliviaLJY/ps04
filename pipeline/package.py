from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import time

from .common import ROOT, dump_json, load_json, read_jsonl, receipt, repo_path, run_dir


def main():
    started=time.time()
    try:
        run=run_dir(sys.argv[1]); review=load_json(run/"review.json")
        check = subprocess.run([str(ROOT/"review/check_content.sh"), str(run)], text=True, capture_output=True)
        if check.returncode != 0: raise RuntimeError(f"could not recompute content review: {check.stderr.strip()}")
        current_review = json.loads(check.stdout)
        if current_review.get("review_id") != review.get("review_id"):
            raise RuntimeError("review is stale: assessed inputs changed after review.json was written")
        if not review.get("passed"): raise RuntimeError("current content review has blocking errors")
        approval_path=run/"approval.json"
        if not approval_path.is_file(): raise RuntimeError("human approval.json is missing")
        approval=load_json(approval_path)
        if approval.get("review_id")!=review["review_id"]: raise RuntimeError("approval is stale: review_id does not match")
        if approval.get("decision")!="approve": raise RuntimeError("human decision is not approve")
        package=run/"package"; package.mkdir(exist_ok=True)
        links_path=package/"publication_links.json"
        links=load_json(links_path) if links_path.exists() else [{"piece_id":f"{i:02d}","substack_url":None,"youtube_url":None} for i in range(1,4)]
        assets=[]; eligible={x["item_id"]:x for x in read_jsonl((run/"eligible.jsonl").open())}; briefs=read_jsonl((run/"briefs.jsonl").open())
        for kind in ("articles","video_scripts"):
            target=package/kind; target.mkdir(exist_ok=True)
            for row in read_jsonl((run/f"{kind}.jsonl").open()):
                src=ROOT/row["path"]; dst=target/src.name; shutil.copy2(src,dst)
                assets.append({"piece_id":row["piece_id"],"kind":kind[:-1] if kind.endswith("s") else kind,"path":repo_path(dst)})
        for brief in briefs:
            seen=[]
            for claim in brief["claims"]:
                for ref in claim["evidence"]:
                    if ref["item_id"] not in seen: seen.append(ref["item_id"])
            notes=[f"# Source Notes — Piece {brief['piece_id']}",""]
            for item_id in seen:
                item=eligible[item_id]; notes.append(f"- [{item['title']}]({item['url']}) — {item['publisher_id']}; version `{item['version_id']}`; published {item.get('published_at')}.")
            path=package/f"sources-{brief['piece_id']}.md"; path.write_text("\n".join(notes)+"\n",encoding="utf-8")
            assets.append({"piece_id":brief["piece_id"],"kind":"source_notes","path":repo_path(path)})
        dump_json(links_path,links)
        manifest={"run_id":load_json(run/"run.json")["run_id"],"review_id":review["review_id"],"assets":assets,
                  "publication_links_path":repo_path(links_path),
                  "manual_steps":["Render each script in Google Vids or HeyGen and apply human corrections.","Publish each reviewed article on Substack and link its video.","Upload each rendered video to YouTube with source notes and the article URL.","Replace null URLs in publication_links.json and verify share access."]}
        dump_json(package/"manifest.json",manifest); print(json.dumps(manifest,ensure_ascii=False,indent=2))
        receipt(run,"prepare-package","completed",started,6,len(assets),tools=["python-file-packager"]); return 0
    except RuntimeError as exc:
        print(exc,file=sys.stderr)
        try: receipt(run,"prepare-package","failed",started,None,0,[str(exc)])
        except Exception: pass
        return 1
    except (IndexError,ValueError,KeyError,json.JSONDecodeError) as exc:
        print(exc,file=sys.stderr); return 2


if __name__=="__main__": raise SystemExit(main())
