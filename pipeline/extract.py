from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import urllib.parse

from .common import ROOT, clean_html, fetch, read_jsonl, receipt, repo_path, run_dir, sha, write_jsonl


def youtube_segments(candidate):
    video_id = candidate["item_id"].split(":", 1)[-1]
    match = re.search(r"(?:v=|youtu\.be/)([\w-]{6,})", candidate.get("url") or "")
    if match:
        video_id = match.group(1)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript = YouTubeTranscriptApi().fetch(video_id, languages=["en"])
        return [{"segment_id": f"yt-{i+1:04d}", "start_seconds": float(row.start),
                 "end_seconds": float(row.start + row.duration), "text": row.text}
                for i, row in enumerate(transcript)]
    except ImportError:
        pass
    except Exception:
        # Fall through to dependency-free public-caption methods.
        pass
    listing = fetch(f"https://www.youtube.com/api/timedtext?type=list&v={urllib.parse.quote(video_id)}")
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(listing)
        track = next(iter(root), None)
        if track is not None:
            lang = track.attrib.get("lang_code", "en"); name = track.attrib.get("name", "")
            raw = fetch("https://www.youtube.com/api/timedtext?" + urllib.parse.urlencode({"v": video_id, "lang": lang, "name": name}))
            transcript = ET.fromstring(raw); out = []
            for i, node in enumerate(transcript):
                start = float(node.attrib.get("start", 0)); duration = float(node.attrib.get("dur", 0))
                out.append({"segment_id": f"yt-{i+1:04d}", "start_seconds": start,
                            "end_seconds": start + duration, "text": clean_html(node.text or "")})
            if out: return out
    except Exception:
        pass
    # Modern YouTube often exposes caption URLs only in the watch-page player JSON.
    page = fetch(candidate["url"]).decode("utf-8", "replace")
    marker = '"captionTracks":'
    start = page.find(marker)
    if start < 0:
        raise RuntimeError("no public caption track")
    tracks, _ = json.JSONDecoder().raw_decode(page[start + len(marker):])
    preferred = next((x for x in tracks if x.get("languageCode", "").startswith("en")), tracks[0])
    raw = fetch(preferred["baseUrl"] + "&fmt=json3")
    payload = json.loads(raw); out = []
    for event in payload.get("events", []):
        words = "".join(x.get("utf8", "") for x in event.get("segs", [])).strip()
        if not words: continue
        start_s = event.get("tStartMs", 0) / 1000.0; duration = event.get("dDurationMs", 0) / 1000.0
        out.append({"segment_id": f"yt-{len(out)+1:04d}", "start_seconds": start_s,
                    "end_seconds": start_s + duration, "text": words})
    if not out: raise RuntimeError("caption track contained no transcript text")
    return out


def transistor_segments(url):
    """Parse public Transistor transcript pages with speaker and time locators."""
    raw = fetch(url.rstrip("/") + "/transcript").decode("utf-8", "replace")
    section = re.search(r'(?is)<section class="episode-description episode-transcript".*?>(.*?)</section>', raw)
    if not section: raise RuntimeError("public timestamped transcript unavailable")
    pattern = re.compile(r'(?is)<cite>(.*?)</cite>\s*<time>.*?>(\d{1,2}):(\d{2})</a></time>\s*<p>(.*?)</p>')
    rows = []
    for speaker, minutes, seconds, body in pattern.findall(section.group(1)):
        start = int(minutes) * 60 + int(seconds)
        rows.append({"segment_id": f"p-{len(rows)+1:04d}", "start_seconds": float(start),
                     "end_seconds": float(start + 20), "text": f"{clean_html(speaker)} {clean_html(body)}"})
    for i in range(len(rows)-1): rows[i]["end_seconds"] = float(rows[i+1]["start_seconds"])
    if not rows: raise RuntimeError("public timestamped transcript unavailable")
    return rows


def extract_one(run, candidate):
    item_id = candidate["item_id"]
    safe = sha(item_id)[:24]
    asset_dir = ROOT / "data" / "assets" / safe
    asset_dir.mkdir(parents=True, exist_ok=True)
    segments = candidate.get("transcript_segments")
    raw_text = candidate.get("content_text")
    if candidate["kind"] == "feed":
        if not raw_text:
            try:
                raw_text = clean_html(fetch(candidate["url"]).decode("utf-8", "replace"))
            except Exception:
                raw_text = clean_html(candidate.get("feed_summary") or "")
                if raw_text:
                    candidate["extraction_note"] = "Source page was inaccessible; retained substantive feed content instead."
        if len(raw_text) < 200:
            raise RuntimeError("substantive written content was not retrievable")
    else:
        if segments is None and candidate.get("transcript_url"):
            payload = fetch(candidate["transcript_url"]).decode("utf-8", "replace")
            try:
                segments = json.loads(payload)
            except json.JSONDecodeError:
                lines = [x.strip() for x in clean_html(payload).splitlines() if x.strip()]
                segments = [{"segment_id": f"s-{i+1:04d}", "start_seconds": i * 20.0,
                             "end_seconds": (i + 1) * 20.0, "text": line} for i, line in enumerate(lines)]
        if segments is None and candidate["kind"] == "youtube":
            segments = youtube_segments(candidate)
        if segments is None and candidate["kind"] == "podcast" and "transistor.fm/" in (candidate.get("url") or ""):
            segments = transistor_segments(candidate["url"])
        if segments is None:
            raise RuntimeError("timestamped transcript unavailable; configure transcript_url")
        raw_text = "\n".join(s.get("text", "") for s in segments)
        if len(raw_text) < 80:
            raise RuntimeError("transcript is too short")
    text_path = asset_dir / f"{sha(raw_text)}.txt"
    if not text_path.exists():
        text_path.write_text(raw_text.strip() + "\n", encoding="utf-8")
    seg_path = None
    if segments is not None:
        seg_path = asset_dir / f"{sha(segments)}.segments.json"
        if not seg_path.exists():
            seg_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    substantive = {k: candidate.get(k) for k in ("item_id", "source_id", "publisher_id", "kind", "title", "url", "published_at", "media_url")}
    substantive.update({"text_hash": sha(raw_text), "segments_hash": sha(segments) if segments is not None else None})
    result = dict(candidate)
    result["version_id"] = sha(substantive)
    result["text_path"] = repo_path(text_path)
    result["segments_path"] = repo_path(seg_path) if seg_path else None
    for temporary in ("content_text", "transcript_segments", "feed_summary", "transcript_url"):
        result.pop(temporary, None)
    return result


def main():
    started = time.time(); errors = []
    try:
        run = run_dir(sys.argv[1])
        candidates = read_jsonl(sys.stdin)
        output = []
        for c in candidates:
            try:
                output.append(extract_one(run, c))
            except Exception as exc:
                errors.append(f"{c.get('item_id', '<unknown>')}: {exc}")
        write_jsonl(output)
        receipt(run, "extract-content", "incomplete" if errors else "completed", started,
                len(candidates), len(output), errors, ["python-urllib", "html-text-extractor", "youtube-transcript-api", "youtube-timedtext"])
        return 1 if errors else 0
    except (IndexError, ValueError) as exc:
        print(exc, file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
