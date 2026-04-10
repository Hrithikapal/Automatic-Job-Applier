# AI Job Application Agent

An end-to-end agentic pipeline that autonomously applies to jobs on your behalf. Give it a queue of job URLs — it tailors your resume, writes a cover letter, opens a real browser, detects the ATS platform, fills every form field intelligently, and clicks Submit.

Built with **LangGraph** (orchestration), **Groq** (LLM inference), **Playwright** (browser automation), and **SQLAlchemy** (candidate DB).

## Table of Contents

- [How to Run the Demo](#how-to-run-the-demo)
- [Candidate Database](#candidate-database)
- [ATS Detection](#ats-detection)
- [Form Field Mapping](#form-field-mapping)
- [Human-in-the-Loop (HITL)](#human-in-the-loop-hitl)
- [Scaling](#scaling)
- [Project Structure](#project-structure)
- [Environment Variables](#environment-variables)

---

## How to Run the Demo

### Prerequisites

- Python 3.11+
- A free [Groq API key](https://console.groq.com/keys)
- Job site credentials (LinkedIn, Workday, etc.) for ATS platforms that require login

### Setup

```bash
# 1. Clone and install
git clone https://github.com/Hrithikapal/Automatic-Job-Applier.git
cd Automatic-Job-Applier
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp .env.example .env
# Edit .env — add your GROQ_API_KEY and job site credentials

# 3. Seed the demo profile and job queue
python demo.py --seed-only

# 4. Run the full pipeline
python demo.py
```

### CLI options

```bash
# Run the demo (seed + process all queued jobs)
python demo.py

# Seed only (don't process jobs)
python demo.py --seed-only

# Reset job queue and re-seed
python demo.py --reseed

# Check queue status
python demo.py --status

# Process jobs directly (without demo wrapper)
python main.py

# Filter by ATS platform
python main.py --platform linkedin

```

### Interactive custom answers setup

```bash
# Walk through 25 common form questions interactively
python setup_answers.py

# Show all stored answers
python setup_answers.py --show

# Add a single answer
python setup_answers.py --add
```

---

## Candidate Database

### Schema (6 tables)

```
users
├── id, full_name, email, phone, location
├── linkedin_url, github_url, portfolio_url
├── resume_path, summary
└── created_at, updated_at

work_experiences
├── user_id (FK → users), company, title, location
├── start_date, end_date (nullable = current role)
└── description (newline-separated bullet points)

educations
├── user_id (FK → users), institution, degree, field_of_study
├── start_date, end_date, gpa (nullable)

skills
├── user_id (FK → users), name
├── category (programming_language | framework | tool | cloud | soft)
└── proficiency (expert | proficient | familiar)

custom_answers
├── user_id (FK → users), key (normalized), value
└── notes (optional context)

jobs
├── url (unique), company, title, ats_platform
├── status (queued | processing | submitted | failed | backlog)
├── failure_reason, unanswered_fields (JSON)
└── job_description_raw, tailored_resume_text
```

### Extending with custom answers

`custom_answers` is a key-value store. Any new answer is automatically picked up on every future run — no code changes needed:

```python
from database.connection import get_session
from database.models import CustomAnswer

with get_session() as session:
    session.add(CustomAnswer(
        user_id=1,
        key="expected_start_date",
        value="As soon as possible",
        notes="Used for any 'when can you start' questions"
    ))
    session.commit()
```

Keys already seeded in the demo profile:

| Key | Value | Used For |
|-----|-------|----------|
| `sponsorship_required` | No | Visa sponsorship questions |
| `work_authorization` | Authorized to work in the US without sponsorship | Work auth dropdowns |
| `notice_period` | 2 weeks | Notice / availability |
| `salary_expectation` | 150kUSD | Salary expectation fields |
| `willing_to_relocate` | Yes | Relocation questions |
| `heard_about_job` | LinkedIn | "How did you hear about us" |
| `gender` | Prefer not to say | EEO demographics |
| `veteran_status` | I am not a veteran | EEO demographics |
| `disability_status` | I do not have a disability | EEO demographics |
| `years_of_experience` | 3 | Experience level dropdowns |
| `highest_education` | Bachelor's Degree | Education level fields |
| `privacy_policy` | Yes | Privacy / data processing consent |

The fuzzy matching engine uses token overlap (threshold >= 0.7), so `salary_expectation` matches form labels like "What is your expected salary?", "Salary expectations", or "Expected compensation".

### Adding jobs to the queue

```python
from job_queue.manager import JobQueueManager
from database.connection import get_session_factory

queue = JobQueueManager(get_session_factory())
queue.add_job(
    url="https://boards.greenhouse.io/yourcompany/jobs/12345",
    company="YourCompany",
    title="Software Engineer"
)
```

Jobs are deduplicated by URL — adding the same URL twice is a no-op.

---

## ATS Detection

Detection uses a **two-pass strategy** with no hardcoded per-URL logic:

### Pass 1 — URL pattern matching (pre-browser, fast)

Regex patterns match common ATS subdomains before the browser even opens. This pre-loads the right credentials and handler.

```
workday    → myworkdayjobs.com, wd*.myworkdayjobs.com, *.workday.com
greenhouse → boards.greenhouse.io, app.greenhouse.io
linkedin   → linkedin.com/jobs, linkedin.com/hiring
lever      → jobs.lever.co, *.lever.co
ashby      → jobs.ashbyhq.com
amazon     → amazon.jobs, hiring.amazon.com
microsoft  → careers.microsoft.com
```

### Pass 2 — DOM fingerprint scoring (post-browser, authoritative)

After navigating to the URL, each platform is scored by counting matches against CSS selectors, `<script>` URL patterns, and `<meta>` tags unique to that platform:

| Signal Type | Points | Example |
|-------------|--------|---------|
| CSS selector match | 2 | `[data-automation-id='jobPostingHeader']` (Workday) |
| Script URL pattern | 1 | `greenhouse.io/*.js` |
| Meta tag match | 2 | `<meta name="generator" content="greenhouse">` |

The highest-scoring platform above the threshold (2 points) wins. This handles redirect chains, white-label ATS deployments, and custom domains that URL matching would miss.

| Platform | Key DOM Signals |
|----------|----------------|
| Workday | `[data-automation-id]` attributes on form fields |
| Greenhouse | `#application_form`, `.application--wrapper` |
| LinkedIn | `[data-job-id]`, `.jobs-apply-button` |
| Lever | `.application-form`, `form.posting-application` |
| Ashby | `[data-testid*='ashby']` attributes |

### Adding a new ATS platform

1. Add URL patterns to `ATS_URL_PATTERNS` in `agents/nodes/ats_detector.py`
2. Add DOM fingerprints (selectors, script patterns, meta tags) to `ATS_DOM_FINGERPRINTS`
3. Create a new handler class in `browser/ats/` extending `BaseATSHandler`
4. Register the handler in `_get_handler()` in `agents/nodes/form_filler.py`

---

## Form Field Mapping

Every field on every ATS form is resolved through a **4-step precedence chain**. Each step either resolves the field (short-circuits) or passes to the next:

### Step 1: Profile DB lookup (confidence: 1.0)

Direct mapping from normalized field labels to profile data. Handles 40+ label variants:

```
"first_name", "firstname"           → user.full_name.split()[0]
"email", "email_address"            → user.email
"phone", "mobile_number"            → user.phone (cleaned, country code stripped)
"country_phone_code"                → "India" / "United States" (from phone prefix)
"linkedin", "linkedin_profile"      → user.linkedin_url
"github", "github_url"              → user.github_url
"city"                              → user.location.split(",")[0]
"how_did_you_hear_about_this_job"   → "" (picks first dropdown option)
```

Phone numbers are cleaned automatically: `"+91 93812 42138"` becomes `"9381242138"` (country code stripped for E.164 format). The country code is extracted separately for country phone code fields.

### Step 2: Custom answers fuzzy match (confidence: overlap score)

Token overlap between the normalized field label and all `custom_answers` keys. Threshold: 0.7.

```
Form label: "Do you require visa sponsorship?"
Normalized: "do_you_require_visa_sponsorship"
Best match: "sponsorship_required" (overlap score: 0.75)
→ Value: "No"
```

This is why custom answers are powerful — one key covers many label variations across different ATS platforms.

### Step 3: LLM inference (confidence: model-reported)

When the field doesn't match the profile or custom answers, the LLM is given:
- Candidate profile summary (name, location, skills, custom answers)
- Job title and description (first 500 chars)
- Field label, type, and available options (for dropdowns)

The LLM responds with `{"value": "...", "confidence": 0.0-1.0}`. If confidence >= `LLM_CONFIDENCE_THRESHOLD` (default 0.7), the answer is used automatically.

- **Model**: Groq `llama-3.3-70b-versatile`
- **Temperature**: 0.1 (low, for consistency)
- **Best for**: Dropdown selection, yes/no questions, inferring experience levels

### Step 4: HITL escalation

If confidence is below threshold or the LLM returns no value, the field is escalated to the human operator. See [Human-in-the-Loop](#human-in-the-loop-hitl).

### What gets logged

- Every field resolution is logged to the terminal: `filled 'Email' = 'you@email.com' [profile]`
- Pre-filled fields (LinkedIn auto-fills contact info) are detected and skipped: `skipping pre-filled 'Email' = 'you@email.com'`
- Fields that go unanswered (HITL timeout) are stored as JSON in `jobs.unanswered_fields`
- After a run, query the jobs table to see exactly which custom answers to add before the next run

### Special field handling

| Field Type | Behavior |
|------------|----------|
| **Dropdowns** (`select`) | LLM picks the best option from available choices. Placeholder values like "Select an option" are treated as empty (not pre-filled). |
| **Typeahead** (autocomplete inputs) | Types the value, waits for suggestions, clicks the first match. |
| **File uploads** (resume, cover letter) | Uses the tailored resume PDF or generated cover letter PDF from earlier pipeline stages. |
| **Radio buttons** (e.g. resume selection) | If one is already checked (LinkedIn pre-selects your latest resume), the section is skipped. |
| **Pre-filled fields** | LinkedIn pre-fills email, phone, and country code from your profile. These are detected via `current_value` and skipped to avoid overwriting. |

---

## Human-in-the-Loop (HITL)

HITL triggers only when the agent genuinely cannot answer a field — something ambiguous, sensitive, or outside the candidate DB and LLM inference.

### Flow

```
Field detected with low confidence
         │
         ▼
┌─────────────────────────────┐
│  Terminal prompt:           │
│  Field: "Clearance level"   │
│  Type: select               │
│  Options: [Secret, TS/SCI]  │
│                             │
│  You have 30 seconds...     │
│  [28] Your answer: █        │
└─────────────────────────────┘
         │
    ┌────┴────┐
    │         │
 Answered   Timeout
    │         │
    ▼         ▼
 Saved to   Job → backlog
 custom_    (skip, move to
 answers    next job)
    │
    ▼
 Continue filling
 (answer reused for
 all future jobs)
```

### The 30-second timeout

- Configurable via `HITL_TIMEOUT_SECONDS` in `.env`
- Uses a non-blocking `threading.Event` so the countdown doesn't freeze the terminal
- If you answer in time, the answer is **immediately saved** to `custom_answers` — you'll never be asked the same question again

### Backlog

Jobs that time out move to `backlog` status. The terminal prints exactly what to add:

```
  ⚠ backlog — 1 unanswered field(s):
    • Clearance level (select)
      hint: add to custom_answers with key 'clearance_level'
```

After adding the answer, re-queue the job:

```python
from job_queue.manager import JobQueueManager
from database.connection import get_session_factory

queue = JobQueueManager(get_session_factory())
queue.requeue_backlog(job_id=5)   # resets status to 'queued'
```

Or add the answer and re-run — it will be picked up automatically:

```python
from database.connection import get_session
from database.models import CustomAnswer

with get_session() as session:
    session.add(CustomAnswer(user_id=1, key="clearance_level", value="Secret"))
    session.commit()
```

---

## Scaling

### Multiple users

The schema already supports multiple users via foreign keys. Every table references `user_id`. To process jobs for a different user:

```bash
python main.py --user-id 2
```

Each user has their own profile, work history, skills, custom answers, and job queue.

### Concurrent agents

Replace SQLite with PostgreSQL (set `DATABASE_URL` in `.env`) and use `SELECT ... FOR UPDATE SKIP LOCKED` in `job_queue/manager.py` — the query structure already supports this. Each agent process calls `dequeue_next()` atomically, so no two agents pick the same job.

```
                    ┌──────────┐
                    │ Job Queue│
                    │ (Postgres)│
                    └────┬─────┘
                         │
            ┌────────────┼────────────┐
            │            │            │
       ┌────▼────┐  ┌───▼─────┐  ┌──▼──────┐
       │ Agent 1 │  │ Agent 2 │  │ Agent 3 │
       │ (LinkedIn)│ │(Workday)│  │(Greenhouse)│
       └─────────┘  └─────────┘  └─────────┘
```

### Job queue infrastructure

For high volume, replace the DB-backed queue with a proper message broker:
- **Redis Streams** — lightweight, built-in delayed retry
- **RabbitMQ** — durable, supports dead-letter queues for failed jobs
- **AWS SQS** — managed, scales automatically

Wrap each `graph.ainvoke()` call in a worker that acks the message only after `submitted` or `backlog` status is confirmed.

### Browser scaling

For running many concurrent browser sessions:
- **Browserless.io** — managed Playwright endpoints, handles browser lifecycle
- **Playwright Cloud** — remote browser instances
- Set `PLAYWRIGHT_WS_ENDPOINT` in `.env` to connect to a remote endpoint instead of launching local Chromium

### Browser stealth

The pipeline includes stealth measures to avoid bot detection by ATS platforms:
- `--disable-blink-features=AutomationControlled` Chrome flag
- `navigator.webdriver` removed via init script
- `window.chrome` runtime object injected
- Modern user agent string (Chrome 131, Windows 10)

---

## Project Structure

```
Automatic-Job-Applier/
├── main.py                  # Job processing loop — dequeues and runs each job
├── demo.py                  # Demo entry point — seed + run + status
├── setup_answers.py         # Interactive CLI for adding custom answers
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
│
├── agents/
│   ├── state.py             # AgentState TypedDict (25 fields)
│   ├── graph.py             # LangGraph StateGraph (10 nodes, conditional routing)
│   └── nodes/
│       ├── job_scraper.py   # Scrape job description (httpx + BeautifulSoup)
│       ├── resume_tailor.py # LLM-tailored resume → PDF
│       ├── cover_letter.py  # LLM-generated cover letter
│       ├── ats_detector.py  # URL pattern + DOM fingerprint detection
│       ├── field_resolver.py# 4-step field resolution chain
│       ├── form_filler.py   # Browser init, sign-in, form fill loop, submit
│       └── hitl.py          # Human-in-the-loop + result recording
│
├── browser/
│   ├── session.py           # Playwright lifecycle + stealth config
│   └── ats/
│       ├── base.py          # Abstract BaseATSHandler interface
│       ├── workday.py       # Workday handler (wizard navigation, Apply Manually)
│       ├── greenhouse.py    # Greenhouse handler (single-page form)
│       ├── linkedin.py      # LinkedIn Easy Apply handler (modal, multi-step)
│       └── lever.py         # Lever handler (single-page form)
│
├── database/
│   ├── models.py            # SQLAlchemy ORM (User, Job, CustomAnswer, etc.)
│   ├── connection.py        # init_db(), get_session(), SQLite WAL mode
│   └── seed.py              # Demo profile + job queue seeder
│
├── job_queue/
│   └── manager.py           # Dequeue, status transitions, stats
│
└── assets/
    └── resumes/
        ├── generate_resume.py   # Demo resume PDF generator (reportlab)
        └── tailored/            # Output directory for tailored PDFs
```

### Pipeline flow

```
scrape_jd → tailor_resume → cover_letter → browser_init → ats_detect → sign_in
                                                                          │
                                                                          ▼
                                                                      fill_form ◄─┐
                                                                          │        │
                                                              ┌───────────┼────────┤
                                                              │           │        │
                                                           pending     form      more
                                                            hitl     complete   sections
                                                              │           │        │
                                                              ▼           ▼        │
                                                            hitl       submit      │
                                                              │           │        │
                                                         ┌────┴────┐      │        │
                                                      answered  timeout   │        │
                                                         │        │      │        │
                                                         └──►fill_form   │        │
                                                                  │      │        │
                                                               record_result ◄────┘
                                                                  │
                                                                 END
```

---

## Environment Variables

| Variable | Required | Default | Used In |
|----------|----------|---------|---------|
| `GROQ_API_KEY` | Yes | — | `resume_tailor.py`, `cover_letter.py`, `field_resolver.py` |
| `DATABASE_URL` | No | `sqlite:///./ai_job_applier.db` | `connection.py` |
| `LINKEDIN_EMAIL` | No | — | `form_filler.py`, `linkedin.py` |
| `LINKEDIN_PASSWORD` | No | — | `form_filler.py`, `linkedin.py` |
| `WORKDAY_EMAIL` | No | — | `form_filler.py` (also used for Amazon/Microsoft jobs) |
| `WORKDAY_PASSWORD` | No | — | `form_filler.py` |
| `GREENHOUSE_EMAIL` | No | — | `form_filler.py` |
| `GREENHOUSE_PASSWORD` | No | — | `form_filler.py` |
| `HITL_TIMEOUT_SECONDS` | No | `30` | `hitl.py` — seconds before moving job to backlog |
| `LLM_CONFIDENCE_THRESHOLD` | No | `0.7` | `form_filler.py` — below this triggers HITL |
| `BROWSER_HEADLESS` | No | `false` | `session.py` — set `true` for CI/production |
| `BROWSER_SLOW_MO` | No | `300` | `session.py` — ms between Playwright actions (lower = faster) |
| `RESUME_PATH` | No | `assets/resumes/hrithika_pal_resume.pdf` | `workday.py` — base resume for Workday Autofill |

> **Note:** Lever and Greenhouse are public job boards — they don't require sign-in credentials. Amazon and Microsoft jobs redirect to Workday, so they use `WORKDAY_EMAIL`/`WORKDAY_PASSWORD`.

---

## License

MIT
