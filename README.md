# Semantic Job-Posting Monitor

Watches target company career pages and ranks open roles by how **semantically**
they match your ideal-role profile — no reliance on job-title keywords. Ships
with two front-ends:

- **Web dashboard** (Next.js on Vercel) — open roles per company, stack-ranked
  by match score, refreshed automatically. *(See "Web dashboard" below.)*
- **CLI / email** (`python -m jobmonitor.run`) — local alerts + optional SMTP
  digest. *(See "Run" below.)*

## Web dashboard (Vercel + GitHub Action)

```
GitHub Action (cron)                 Vercel
┌───────────────────────┐            ┌──────────────────────┐
│ jobmonitor.export     │  commits   │ Next.js app reads    │
│  scrape + score all   │ ─────────▶ │ data/results.json    │
│  -> data/results.json │  redeploy  │ -> ranked dashboard  │
└───────────────────────┘            └──────────────────────┘
```

The web app and the scraper never run on the same box: a scheduled GitHub
Action (`.github/workflows/refresh.yml`) does the heavy lifting (Playwright +
embeddings) every 6 hours, writes `data/results.json`, and commits it. Vercel
serves the dashboard as static pages and redeploys whenever that file changes.

**One-time setup:**

1. **Import the repo into Vercel** → New Project → select this repo. Framework
   preset auto-detects **Next.js**; root directory is the repo root. Deploy.
2. **Enable the Action** → in GitHub, the workflow runs on its 6-hour schedule;
   trigger the first run manually via **Actions → Refresh job matches → Run
   workflow**. It commits live data, which triggers a Vercel deploy.
   - The workflow needs write access — GitHub's default `GITHUB_TOKEN`
     (Settings → Actions → General → Workflow permissions → *Read and write*)
     is sufficient.
3. (Optional) tune `MATCH_THRESHOLD` as a repository **Variable**.

**Local preview of the dashboard:**

```bash
npm install
npm run dev          # http://localhost:3000  (reads data/results.json)
python -m jobmonitor.export   # regenerate data/results.json locally
```

---

## CLI monitor

The pieces below also work standalone, fully local, no cloud required.

## How it works

```
targets.json ──▶ scraper ──▶ new postings ──▶ matcher ──▶ alerts
(companies +     (requests/   (vs. local      (embeddings +  (matches.log
 careers URLs)    Playwright)   seen-store)     cosine sim)    + email)
                                                    ▲
                                            ideal_roles/*.txt
                                          (sample target roles)
```

1. **`targets.json`** — the companies you watch and their careers URLs.
2. **Scraper** (`jobmonitor/scraper.py`) — fetches each listing page, parses out
   individual postings, follows each link for the full description, and skips
   anything already recorded in the local seen-store.
3. **Matcher** (`jobmonitor/matcher.py`) — embeds each new posting and every file
   in `ideal_roles/`, then scores the posting by its highest cosine similarity to
   any of your ideal roles. Above the threshold → flagged.
4. **Alerts** (`jobmonitor/alerts.py`) — writes flagged matches to `matches.log`
   and (optionally) emails you a digest via SMTP.

## Install

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Needed only if a career page is JavaScript-rendered (the scraper auto-detects
# this and falls back to Playwright):
playwright install chromium
```

The default embedding backend is **sentence-transformers** — free and fully
local (the first run downloads the `all-MiniLM-L6-v2` model, ~80 MB). To use
OpenAI instead, see "Configuration" below.

## Configure

### 1. Companies to watch — `targets.json`

```json
[
  { "company": "Cribl", "url": "https://cribl.io/careers/" }
]
```

Optional per-target fields:

| field           | default  | meaning                                                            |
| --------------- | -------- | ------------------------------------------------------------------ |
| `render`        | `"auto"` | `"static"` (requests only), `"js"` (Playwright only), or `"auto"`  |
| `link_selector` | `null`   | CSS selector for posting links, overriding the generic heuristic   |

`targets.json` ships pre-seeded with: Cribl, Zillow, Snowflake, Dynatrace,
Datadog, HubSpot, Wasabi Technologies, Cyera, and Snyk. ("Boston Tech Companies"
from the brief isn't a single page — add specific companies/URLs as you find
them.)

### 2. Ideal roles — `ideal_roles/*.txt`

Drop one `.txt` file per sample job description you'd love to land. Two are
included to calibrate matching (a Cribl Sr. PM – Pipeline Generation role and a
Distribution Intelligence / AI Strategy PM role). The more representative
samples you add, the better the matching.

### 3. Settings — `.env` (optional)

Copy `.env.example` to `.env`. Defaults work with no config. Key options:

- `MATCH_THRESHOLD` (default `0.75`) — similarity cutoff for a flag.
- `EMBEDDING_BACKEND` — `sentence-transformers` (default) or `openai`.
  For OpenAI set `OPENAI_API_KEY` and optionally
  `OPENAI_EMBED_MODEL=text-embedding-ada-002`.
- `SMTP_*` — set `SMTP_ENABLED=true` plus host/credentials to receive email
  digests. For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833).

## Run

```bash
python -m jobmonitor.run                 # one full pass over all targets
python -m jobmonitor.run --company Cribl  # just one company
python -m jobmonitor.run --threshold 0.8  # override threshold for this run
python -m jobmonitor.run --dry-run        # score but don't persist state / email
python -m jobmonitor.run --reprocess      # re-score everything, ignoring seen-store
```

First run is the noisiest — every posting is "new". After that, only postings
not yet in `state/seen.json` are fetched and scored.

Output: flagged matches are appended to `matches.log`, one tab-separated line:

```
<timestamp>  <company>  <title>  score=<0.xxxx>  matched_role=<file>  <url>
```

## Schedule it

### macOS / Linux (cron) — every 6 hours

```cron
0 */6 * * * cd /path/to/Email-Agent && /path/to/Email-Agent/.venv/bin/python -m jobmonitor.run >> cron.log 2>&1
```

Edit with `crontab -e`.

### Windows (Task Scheduler)

Create a Basic Task → trigger Daily/recurring → Action "Start a program":

- Program: `C:\path\to\Email-Agent\.venv\Scripts\python.exe`
- Arguments: `-m jobmonitor.run`
- Start in: `C:\path\to\Email-Agent`

## Tuning notes

- **Career pages vary wildly.** The generic parser keeps links whose URL looks
  like a job detail (`/jobs/`, `greenhouse.io`, `lever.co`, `myworkdayjobs`,
  etc.). If a site returns 0 or junk postings, set a `link_selector` for that
  target (inspect the page's HTML to find the right CSS selector), or set
  `"render": "js"` to force Playwright.
- **Threshold calibration.** Run with `--dry-run` and watch the printed scores
  for postings you know are good vs. bad, then set `MATCH_THRESHOLD` between
  them. 0.75 is a reasonable start for `all-MiniLM-L6-v2`; OpenAI embeddings
  often sit a bit higher.
- **Be a good citizen.** Scraping happens at human pace and only fetches new
  postings; keep the schedule modest (a few times a day).
```
