#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
if [ "$#" -ne 1 ]; then echo "usage: collect_sources.sh RUN_DIR" >&2; exit 2; fi
RUN_DIR="$1"
mkdir -p "$RUN_DIR/candidates"
COLLECT_STATUS=0
for KIND in feeds youtube podcasts; do
  "collectors/fetch_${KIND}.sh" "$RUN_DIR" > "$RUN_DIR/candidates/${KIND}.jsonl"
  RC=$?
  if [ "$RC" -eq 2 ]; then exit 2; fi
  if [ "$RC" -ne 0 ]; then COLLECT_STATUS=1; fi
done
awk 'FNR==1 && NR!=1 { } { print }' "$RUN_DIR/candidates/feeds.jsonl" "$RUN_DIR/candidates/youtube.jsonl" "$RUN_DIR/candidates/podcasts.jsonl" > "$RUN_DIR/candidates.jsonl"
cat "$RUN_DIR/candidates.jsonl" | processing/extract_content.sh "$RUN_DIR" > "$RUN_DIR/items.jsonl"
EXTRACT_STATUS=$?
if [ "$EXTRACT_STATUS" -eq 2 ]; then exit 2; fi
if [ "$EXTRACT_STATUS" -ne 0 ]; then COLLECT_STATUS=1; fi
cat "$RUN_DIR/items.jsonl" | data/store.sh upsert "$RUN_DIR" > "$RUN_DIR/changes.jsonl" || exit $?
data/store.sh list | tee "$RUN_DIR/corpus.jsonl" | processing/filter_items.sh "$RUN_DIR" > "$RUN_DIR/eligible.jsonl" || exit $?
exit "$COLLECT_STATUS"
