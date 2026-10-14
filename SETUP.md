# Setup and operation

## Requirements

- macOS or Linux with Bash, Python 3.9+, `curl`, and standard Unix tools.
- Network access to configured public feeds and source pages.
- A Google AI Studio API key for the no-cost Gemini editorial path. The configured `gemini-3.1-flash-lite` model has free-tier pricing and rate limits; free-tier inputs may be used to improve Google's products.

Create the local environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env.local
```

Create a key from the [Google AI Studio API keys page](https://aistudio.google.com/app/apikey), then place it in `.env.local` as `GEMINI_API_KEY`. Do not commit that file. The pipeline reads it without printing it. No billing upgrade is required for the supported free tier, but account eligibility and rate limits are controlled by Google.

## Run

```bash
bash run.sh
```

The command prints a summary and leaves the immutable run under `runs/RUN_ID/`. If the key is present, model receipts identify `gemini-3.1-flash-lite`; otherwise the run uses a deterministic test fallback and is not suitable as the assignment's AI-backed submission run.

After checking the evidence, decisions, drafts, and `review.json`, create `approval.json` using the shape in `examples/approval.json`. The `review_id` must match exactly. Then run:

```bash
bash run.sh --package runs/RUN_ID
```

The packager recomputes the review fingerprint, refuses stale approval, and creates the production handoff only when review passes.

## Independent component replay

Every required stage can be run separately. Examples:

```bash
cat runs/RUN_ID/corpus.jsonl | processing/filter_items.sh runs/RUN_ID
cat runs/RUN_ID/eligible.jsonl | editorial/select_items.sh runs/RUN_ID
data/store.sh get ITEM_ID VERSION_ID
reporting/summarize_run.sh runs/RUN_ID
tests/contract_test.sh
```

`AI_COMMAND` is a provider-neutral JSON-in/JSON-out override. Set it to another executable to use a different model provider. The executable receives `{stage, prompt, input}` on standard input and must emit only the required JSON value.

## Known collection behavior

- YouTube captions use `youtube-transcript-api`, with public-caption fallbacks. Videos without public captions are retained as explicit extraction failures.
- Public Transistor transcript pages are parsed into speaker-attributed timestamp segments. Other podcast hosts need a configured `transcript_url` or a focused adapter.
- RSS extraction prefers the source page and retains substantive feed content when the page blocks automated access. The evidence record notes that fallback.
- Partial collection never becomes a successful empty result; usable evidence continues and failures remain in receipts and the summary.
