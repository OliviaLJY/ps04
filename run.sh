#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

# Prefer the configured no-cost Gemini adapter; otherwise retain the inspectable
# deterministic fallback. Never source env files as shell code.
if [ -z "${AI_COMMAND:-}" ]; then
  if [ -n "${GEMINI_API_KEY:-}" ] || { [ -f .env.local ] && awk -F= '$1=="GEMINI_API_KEY" && length($2)>0 {found=1} END {exit !found}' .env.local; }; then
    export AI_COMMAND="$ROOT/.venv/bin/python $ROOT/providers/gemini_command.py"
    export AI_MODEL_NAME="${GEMINI_MODEL:-gemini-flash-lite-latest}"
  fi
fi

if [ "${1:-}" = "--package" ]; then
  if [ "$#" -ne 2 ]; then echo "usage: run.sh --package RUN_DIR" >&2; exit 2; fi
  RUN_DIR="$2"
  review/check_content.sh "$RUN_DIR" > "$RUN_DIR/review.json" || exit $?
  publishing/prepare_package.sh "$RUN_DIR" > "$RUN_DIR/package-output.json"
  PACKAGE_RC=$?
  reporting/summarize_run.sh "$RUN_DIR" | tee "$RUN_DIR/summary.json"
  exit "$PACKAGE_RC"
fi
if [ "$#" -ne 0 ]; then echo "usage: run.sh [--package RUN_DIR]" >&2; exit 2; fi

python3 - config/project.json config/sources.json <<'PY' || exit 2
import json,sys
p=json.load(open(sys.argv[1])); s=json.load(open(sys.argv[2]))
required=("publication_name","topic","audience","central_question")
assert all(isinstance(p.get(k),str) and p[k].strip() for k in required), "project configuration is incomplete"
assert isinstance(s,list) and s, "sources configuration is empty"
for x in s:
    assert all(x.get(k) for k in ("source_id","publisher_id","kind","url")), "invalid source definition"
    assert x["kind"] in ("feed","youtube","podcast"), "invalid source kind"
PY

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RUN_DIR="runs/$RUN_ID"
mkdir -p "$RUN_DIR/config" "$RUN_DIR/prompts" "$RUN_DIR/logs"
cp config/project.json config/sources.json config/editorial_policy.md "$RUN_DIR/config/"
cp prompts/select_items.md prompts/create_briefs.md prompts/write_articles.md prompts/write_video_scripts.md "$RUN_DIR/prompts/"
PREVIOUS="$(find runs -mindepth 1 -maxdepth 1 -type d ! -name "$RUN_ID" | sort | tail -1)"
python3 - "$RUN_DIR/run.json" "$RUN_ID" "$PREVIOUS" <<'PY'
import datetime,json,sys
now=datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
json.dump({"run_id":sys.argv[2],"started_at":now.isoformat().replace("+00:00","Z"),"as_of_date":now.date().isoformat(),"mode":"live","previous_run_id":sys.argv[3].split("/")[-1] if sys.argv[3] else None},open(sys.argv[1],"w"),indent=2)
open(sys.argv[1],"a").write("\n")
PY

data/store.sh init || exit $?
workflows/collect_sources.sh "$RUN_DIR"
COLLECT_RC=$?
if [ -s "$RUN_DIR/eligible.jsonl" ]; then
  workflows/create_series.sh "$RUN_DIR"
fi
reporting/summarize_run.sh "$RUN_DIR" | tee "$RUN_DIR/summary.json"
if [ "$COLLECT_RC" -eq 2 ]; then exit 2; fi
exit 0
