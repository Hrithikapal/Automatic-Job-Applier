# AI Job Application Agent

An end-to-end agentic pipeline that autonomously applies to jobs on your behalf. Give it a queue of job URLs — it tailors your resume, writes a cover letter, opens a real browser, detects the ATS, fills every form field intelligently, and submits .

---

## Quick Start (Demo)

```bash
# 1. Clone and install
git clone <repo-url>
cd ai-job-applier
pip install -r requirements.txt
playwright install chromium

# 2. Configure credentials
cp .env.example .env
# Edit .env — add your GROQ_API_KEY and job site credentials

# 3. Seed the demo profile and job queue
python demo.py --seed-only

# 4. Run the full pipeline
python demo.py
```

The demo seeds **Alex Chen** (mid-level SWE, 3.5 yrs experience) and queues 6 real jobs across Workday, Greenhouse, and Lever.

---

## Candidate Database

### Schema

| Table | Purpose |
|---|---|
| `users` | Personal info, contact details, resume path, professional summary |
| `work_experiences` | Job history with company, title, dates, and bullet-point descriptions |
| `educations` | Degrees, institutions, field of study, GPA |
| `skills` | Categorized skills with proficiency levels |
| `custom_answers` | Key-value store for non-resume questions (the important one) |
| `jobs` | Queue + status tracking for every job URL |

### Extending with custom answers

`custom_answers` is a key-value store. Add any new answer and it's automatically picked up on every future run — no code changes:

```python
from database.connection import get_session
from database.models import CustomAnswer

with get_session() as session:
    session.add(CustomAnswer(
        user_id=1,
        key="expected_start_date",
        value="Immediately",
        notes="Used for any 'when can you start' questions"
    ))
    session.commit()
```

Common keys already seeded: `sponsorship_required`, `work_authorization`, `notice_period`, `salary_expectation`, `willing_to_relocate`, `heard_about_job`, `gender`, `veteran_status`, `disability_status`, `remote_preference`.

### Adding jobs to the queue

```python
from queue.manager import JobQueueManager
from database.connection import get_session_factory

queue = JobQueueManager(get_session_factory())
queue.add_job("https://boards.greenhouse.io/yourcompany/jobs/12345")
```

---

## ATS Detection

Detection uses a two-pass strategy with no hardcoded per-URL logic:

**Pass 1 — URL pattern matching** (fast, pre-browser): Regex patterns match common ATS subdomains (`myworkdayjobs.com`, `greenhouse.io`, `lever.co`, `linkedin.com/jobs`, `ashbyhq.com`). Used to pre-load the right credentials before the browser opens.

**Pass 2 — DOM fingerprint scoring** (authoritative, post-browser): After navigating to the URL, each platform is scored by counting matching CSS selectors, `<script>` URL patterns, and `<meta>` tags unique to that platform. The highest-scoring platform above a threshold wins. This handles redirect chains, white-label ATS deployments, and custom domains.

| Platform | Key DOM Signals |
|---|---|
| Workday | `[data-automation-id]` attributes throughout |
| Greenhouse | `#application_form`, `.application--wrapper` |
| Lever | `.application-form`, `form.posting-application` |
| LinkedIn | `[data-job-id]`, `.jobs-easy-apply-content` |
| Ashby | `[data-testid*='ashby']` attributes |

---

## Form Field Mapping

Every field on every ATS form is resolved through a **4-step precedence chain**:

1. **Profile DB** — direct lookup for canonical fields (name, email, phone, location, LinkedIn URL, resume file). Resolved with 100% confidence.

2. **Custom answers** — fuzzy key matching (token overlap >= 0.7) against your `custom_answers` table. Handles sponsorship, salary, notice period, EEO demographics, and anything else you've pre-answered.

3. **LLM inference** — The LLM is given the candidate's full profile + job description and asked to infer the best answer with a confidence score. Temperature 0.3 for consistency. If confidence >= `LLM_CONFIDENCE_THRESHOLD` (.env), the answer is used automatically.

4. **HITL (human-in-the-loop)** — triggered when confidence is too low. See next section.

**What gets logged**: any field that goes unanswered (HITL timeout or no basis for inference) is stored as JSON in `jobs.unanswered_fields`. After a run, query your jobs table to see exactly what to add to `custom_answers` before the next run.

---

## Human-in-the-Loop (HITL)

HITL triggers only when the agent genuinely cannot answer a field with confidence — something ambiguous, sensitive, or outside the candidate DB and LLM inference.

**Flow:**
1. Agent pauses on the field and prints a terminal prompt with the field label, type, and surrounding context
2. A **30-second countdown** begins
3. **User answers in time** -> answer fills the field, gets saved to `custom_answers` for all future runs, agent continues
4. **No response / timeout** -> job moves to `backlog`, agent immediately starts the next job in the queue

**Submission is always automatic** — once all fields are resolved (or skipped), the agent submits without any confirmation step.

**Backlog**: jobs in `backlog` status can be re-queued after you've added the missing answers to `custom_answers`:

```python
queue.requeue_backlog(job_id=5)
```

---

## Scaling

**Multiple users**: The schema already supports multiple users via foreign keys. Swap `user_id=1` hardcode in `main.py` for a CLI argument or environment variable.

**Concurrent agents**: Replace the SQLite `jobs` table with PostgreSQL and use `SELECT ... FOR UPDATE SKIP LOCKED` in `queue/manager.py` (the query is already written this way). Each agent process calls `dequeue_next()` atomically — no double-processing.

**Job queue infrastructure**: For high volume, replace the DB-backed queue with a proper message broker (Redis Streams, RabbitMQ, or SQS). Wrap each `graph.ainvoke()` call in a worker that acks the message only after `submitted` or `backlog` status is confirmed.

**Browser scaling**: Run multiple Playwright browser instances behind a Browserless or Playwright Cloud endpoint. Set `PLAYWRIGHT_WS_ENDPOINT` in `.env` to connect remotely instead of launching a local Chromium.

---

## Project Structure

```
├── main.py              # Processing loop — dequeues and runs jobs
├── demo.py              # Demo entry point — seed + run + status table
├── database/
│   ├── models.py        # SQLAlchemy ORM models (6 tables)
│   ├── connection.py    # init_db(), get_session()
│   └── seed.py          # Demo user Alex Chen + 6 job URLs
├── agents/
│   ├── state.py         # AgentState TypedDict
│   ├── graph.py         # LangGraph StateGraph
│   └── nodes/           # One file per pipeline stage
├── browser/
│   ├── session.py       # Playwright BrowserSession
│   └── ats/             # Per-platform ATS handlers
├── queue/
│   └── manager.py       # Job queue operations
└── assets/resumes/      # Resume PDFs
```
