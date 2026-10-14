from __future__ import annotations

import argparse
import email.utils
import pathlib
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

from .common import fetch, load_json, now, receipt, run_dir, sha, write_jsonl


def text(node, names):
    for child in list(node):
        if child.tag.split("}")[-1] in names and child.text:
            return child.text.strip()
    return None


def iso_date(value):
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=__import__("datetime").timezone.utc)
        return parsed.astimezone(__import__("datetime").timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        try:
            return __import__("datetime").datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(__import__("datetime").timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            return value


def link_of(entry):
    for child in list(entry):
        if child.tag.split("}")[-1] == "link":
            href = child.attrib.get("href")
            rel = child.attrib.get("rel", "alternate")
            if href and rel in ("alternate", ""):
                return href
            if child.text and child.text.strip():
                return child.text.strip()
    return text(entry, {"guid", "id"})


def entries(root):
    return [x for x in root.iter() if x.tag.split("}")[-1] in ("item", "entry")]


def parse_source(source, kind, retrieved):
    raw = fetch(source["url"])
    root = ET.fromstring(raw)
    records = []
    limit = int(source.get("limit", 10))
    for entry in entries(root)[:limit]:
        url = link_of(entry)
        title = text(entry, {"title"}) or "Untitled"
        pub = iso_date(text(entry, {"pubDate", "published", "updated", "date"}))
        native = text(entry, {"videoId", "guid", "id"}) or url or title
        media = None
        for child in list(entry):
            local = child.tag.split("}")[-1]
            if local in ("enclosure", "content") and child.attrib.get("url"):
                if child.attrib.get("type", "").startswith(("audio/", "video/")) or local == "enclosure":
                    media = child.attrib["url"]
        description = text(entry, {"description", "summary", "content"})
        prefix = {"feed": "feed", "youtube": "youtube", "podcast": "podcast"}[kind]
        if kind == "youtube":
            match = re.search(r"(?:v=|youtu\.be/)([\w-]{6,})", url or "")
            if match:
                native = match.group(1)
        item = {
            "item_id": f"{prefix}:{sha(str(native))[:20]}", "source_id": source["source_id"],
            "publisher_id": source["publisher_id"], "kind": kind, "title": title, "url": url,
            "published_at": pub, "retrieved_at": retrieved, "media_url": media,
        }
        if description:
            item["feed_summary"] = description
        if source.get("transcript_url"):
            item["transcript_url"] = source["transcript_url"].replace("{item_id}", str(native))
        records.append(item)
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["feed", "youtube", "podcast"])
    parser.add_argument("run_dir")
    args = parser.parse_args()
    started = time.time()
    errors, records = [], []
    try:
        run = run_dir(args.run_dir)
        sources = load_json(run / "config" / "sources.json")
        selected = [s for s in sources if s.get("kind") == args.kind]
        if not selected:
            errors.append(f"no configured {args.kind} sources")
        retrieved = now()
        for source in selected:
            try:
                records.extend(parse_source(source, args.kind, retrieved))
            except Exception as exc:
                errors.append(f"{source.get('source_id', '<unknown>')}: {exc}")
        write_jsonl(records)
        status = "incomplete" if errors else "completed"
        receipt(run, f"collect-{args.kind}", status, started, len(selected), len(records), errors,
                ["python-urllib", "xml.etree.ElementTree"])
        return 1 if errors else 0
    except (ValueError, KeyError) as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
