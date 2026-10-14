#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
if [ "$#" -ne 1 ]; then echo "usage: create_series.sh RUN_DIR" >&2; exit 2; fi
RUN_DIR="$1"
cat "$RUN_DIR/eligible.jsonl" | editorial/select_items.sh "$RUN_DIR" > "$RUN_DIR/decisions.jsonl" || exit $?
cat "$RUN_DIR/decisions.jsonl" | editorial/create_briefs.sh "$RUN_DIR" > "$RUN_DIR/briefs.jsonl" || exit $?
cat "$RUN_DIR/briefs.jsonl" | content/write_articles.sh "$RUN_DIR" > "$RUN_DIR/articles.jsonl" || exit $?
cat "$RUN_DIR/briefs.jsonl" | content/write_video_scripts.sh "$RUN_DIR" > "$RUN_DIR/video_scripts.jsonl" || exit $?
review/check_content.sh "$RUN_DIR" > "$RUN_DIR/review.json" || exit $?
