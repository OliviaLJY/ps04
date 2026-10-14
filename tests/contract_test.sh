#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TEST_RUN="runs/.contract-test-$$"
TEST_STORE="${TMPDIR:-/tmp}/ps04-contract-store-$$"
trap 'rm -rf "$TEST_RUN" "$TEST_STORE"' EXIT
mkdir -p "$TEST_RUN/config" "$TEST_RUN/prompts" "$TEST_RUN/logs"
cp config/* "$TEST_RUN/config/"
cp prompts/* "$TEST_RUN/prompts/"
cp examples/run.json "$TEST_RUN/run.json"

# Freshness boundaries and all four exclusion reasons.
processing/filter_items.sh "$TEST_RUN" < examples/filter_input.jsonl > "$TEST_RUN/filter-actual.jsonl"
python3 - "$TEST_RUN" <<'PY'
import json,sys,pathlib
r=pathlib.Path(sys.argv[1])
got=[json.loads(x)["item_id"] for x in open(r/"filter-actual.jsonl")]
exp=json.load(open("examples/filter_expected.json"))["eligible_item_ids"]
assert got==exp,(got,exp)
reasons=[json.loads(x)["reason"] for x in open(r/"exclusions.jsonl")]
assert reasons==["outside_window","unknown_date","future_date","invalid_date"],reasons
PY

# New, unchanged, changed, and duplicate-within-ingestion storage behavior.
export EVIDENCE_DIR="$TEST_STORE"
data/store.sh init
data/store.sh upsert "$TEST_RUN" < examples/items.jsonl > "$TEST_RUN/initial-changes.jsonl"
data/store.sh upsert "$TEST_RUN" < examples/replay_items.jsonl > "$TEST_RUN/replay-changes.jsonl"
python3 - "$TEST_RUN" <<'PY'
import json,sys,pathlib
r=pathlib.Path(sys.argv[1])
def rows(p): return [json.loads(x) for x in open(p)]
assert rows("examples/initial_changes_expected.jsonl")==rows(r/"initial-changes.jsonl")
assert rows("examples/replay_changes_expected.jsonl")==rows(r/"replay-changes.jsonl")
PY
COUNT="$(data/store.sh list | wc -l | tr -d ' ')"
[ "$COUNT" = "3" ]

# Independent stage contracts: selection -> briefs -> drafts -> review.
python3 - "$TEST_RUN" <<'PY'
import json,sys,pathlib
r=pathlib.Path(sys.argv[1]); base=[json.loads(x) for x in open("examples/items.jsonl")]
kinds=("feed","youtube","podcast"); rows=[]
for i in range(9):
    x=dict(base[i%3]); x["item_id"]=f"{kinds[i%3]}:contract-{i+1}"; x["version_id"]=f"contract-version-{i+1}"
    x["publisher_id"]=f"contract-publisher-{i+1}"; x["title"]=f"Contract evidence {i+1}"
    x["text_path"]="tests/fixtures/feed.txt" if kinds[i%3]=="feed" else "tests/fixtures/media.txt"
    x["segments_path"]=None if kinds[i%3]=="feed" else "tests/fixtures/segments.json"
    rows.append(x)
with open(r/"eligible.jsonl","w") as f:
    for x in rows: f.write(json.dumps(x,separators=(",",":"))+"\n")
PY
editorial/select_items.sh "$TEST_RUN" < "$TEST_RUN/eligible.jsonl" > "$TEST_RUN/decisions.jsonl"
editorial/create_briefs.sh "$TEST_RUN" < "$TEST_RUN/decisions.jsonl" > "$TEST_RUN/briefs.jsonl"
content/write_articles.sh "$TEST_RUN" < "$TEST_RUN/briefs.jsonl" > "$TEST_RUN/articles.jsonl"
content/write_video_scripts.sh "$TEST_RUN" < "$TEST_RUN/briefs.jsonl" > "$TEST_RUN/video_scripts.jsonl"
review/check_content.sh "$TEST_RUN" > "$TEST_RUN/review.json"
python3 - "$TEST_RUN/review.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1])); assert r["passed"],r
PY
# Packaging accepts a matching approval but detects changes made after review.
python3 - "$TEST_RUN" <<'PY'
import datetime,json,sys,pathlib
r=pathlib.Path(sys.argv[1]); review=json.load(open(r/"review.json"))
json.dump({"review_id":review["review_id"],"decision":"approve","reviewer":"Contract-test fixture",
           "reviewed_at":"2026-10-08T15:00:00Z","notes":"Automated fixture only; not publication approval."},open(r/"approval.json","w"),indent=2)
PY
publishing/prepare_package.sh "$TEST_RUN" > "$TEST_RUN/package-output.json"
printf '\npost-review mutation\n' >> "$TEST_RUN/articles/01.md"
if publishing/prepare_package.sh "$TEST_RUN" >/dev/null 2>&1; then
  echo "packager accepted a stale review" >&2; exit 1
fi
echo "All contract tests passed."
