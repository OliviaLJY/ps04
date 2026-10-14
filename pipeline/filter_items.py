from __future__ import annotations

import datetime as dt
import sys
import time

from .common import dump_json, load_json, read_jsonl, receipt, run_dir, write_jsonl


def main():
    started = time.time()
    try:
        run = run_dir(sys.argv[1]); records = read_jsonl(sys.stdin)
        as_of = dt.date.fromisoformat(load_json(run / "run.json")["as_of_date"])
        start = as_of - dt.timedelta(days=29); eligible = []; exclusions = []
        for item in records:
            value = item.get("published_at")
            reason = detail = None
            if value is None:
                reason, detail = "unknown_date", "publication date is absent"
            else:
                try:
                    date = dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
                    if date > as_of: reason, detail = "future_date", f"{date} is after {as_of}"
                    elif date < start: reason, detail = "outside_window", f"{date} is before {start}"
                except Exception:
                    reason, detail = "invalid_date", f"cannot parse {value!r}"
            if reason:
                exclusions.append({"item_id": item["item_id"], "version_id": item["version_id"], "reason": reason, "detail": detail})
            else:
                eligible.append(item)
        with (run / "exclusions.jsonl").open("w", encoding="utf-8") as f: write_jsonl(exclusions, f)
        write_jsonl(eligible)
        receipt(run, "filter-items", "completed", started, len(records), len(eligible), tools=["python-datetime"])
        return 0
    except (IndexError, ValueError, KeyError) as exc:
        print(exc, file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
