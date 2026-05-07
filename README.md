# Email Job-Search Agent

Watches your Gmail and a list of target companies' career boards for Product
Manager / Data PM / AI PM roles, tailors your resume to each match, and emails
you a digest with the tailored resumes attached.

## What it does

1. **Gmail scrape.** Searches the last N days of your inbox for job-related
   emails from your target companies (recruiter outreach, listing alerts).
2. **ATS poll.** Hits the public job-board APIs of every target company:
   Greenhouse, Lever, Ashby, and best-effort Workday.
3. **Match.** Filters titles with cheap keyword rules; uses Claude only for
   borderline cases (Product Lead, Head of Product, etc.).
4. **Tailor.** For each match, uses Claude to produce a resume tailored to the
   role. Hard rule in the prompt: **never invent or change figures, employers,
   dates, titles, or technologies** — only rephrase, reorder, and reweight.
5. **Notify.** Sends you a digest email (from your own Gmail account) with the
   tailored resumes attached.

State is tracked in SQLite, so you only get alerted about each posting once.

## Setup

### 1. Install

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and NOTIFY_EMAIL in .env
```

### 2. Configure Google OAuth (for Gmail)

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a project
2. Enable the **Gmail API** for the project
3. Configure OAuth consent screen (External, your own email as test user)
4. Create OAuth 2.0 Client ID → **Desktop app** → download the JSON
5. Save it to `./secrets/client_secret.json` (or set `GOOGLE_CLIENT_SECRETS` in
   `.env` to point elsewhere)

First run will pop a browser asking you to grant Gmail read + send access.
After that, the token is cached.

### 3. Add your master resume

Replace `config/resume_master.md` with your actual resume in markdown. The
agent will refuse to run while the placeholder is still in place.

### 4. Add target companies

Edit `config/companies.yaml`. Each entry needs a `name` and at least one ATS
handle. To find a handle, look at the company's career page URL:

| Career page                              | ATS         | Handle    |
| ---------------------------------------- | ----------- | --------- |
| `boards.greenhouse.io/stripe`            | Greenhouse  | `stripe`  |
| `jobs.lever.co/netflix`                  | Lever       | `netflix` |
| `jobs.ashbyhq.com/anthropic`             | Ashby       | `anthropic` |
| `xyz.wd1.myworkdayjobs.com/External`     | Workday     | tenant=`xyz`, host=`wd1`, site=`External` |

Example:

```yaml
companies:
  - name: Anthropic
    ashby: anthropic
  - name: Stripe
    greenhouse: stripe
  - name: Netflix
    workday:
      tenant: netflix
      site: Netflix_External
      host: wd1
```

### 5. Tune settings

`config/settings.yaml` controls target roles, Gmail lookback window, model
choice, and per-run tailoring cap.

## Run

```bash
python -m email_agent.main
```

Schedule it with cron / launchd / GitHub Actions for daily runs:

```cron
0 8 * * * cd /path/to/Email-Agent && /usr/bin/python -m email_agent.main >> agent.log 2>&1
```

## Project layout

```
config/
  settings.yaml        # roles, model, lookback window
  companies.yaml       # target companies + ATS handles
  resume_master.md     # your master resume — paste here
src/email_agent/
  ats/                 # Greenhouse / Lever / Ashby / Workday clients
  gmail_client.py      # OAuth, inbox scrape, send
  matcher.py           # title prefilter + LLM judge
  tailor.py            # Claude resume tailoring (with prompt caching)
  notifier.py          # outbox files + Gmail digest
  state.py             # SQLite seen-jobs store
  main.py              # orchestrator
```

## Notes

- **Resume integrity.** The tailor prompt is deliberate and strict: no
  fabricated metrics, employers, dates, or technologies. Read
  `src/email_agent/tailor.py` if you want to adjust the rules.
- **Cost guard.** `max_tailored_per_run` (default 10) caps how many resumes
  Claude tailors per run. Matches above the cap are still recorded; they'll
  just wait for the next run.
- **Workday is best-effort.** Workday tenants vary; if a company's endpoint
  shape diverges, that company will silently return 0 jobs. Check the agent
  logs.
- **Gmail scope.** We use `gmail.readonly` + `gmail.send`. We never modify
  or delete email.
