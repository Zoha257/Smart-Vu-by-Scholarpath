# VU Lecture Intelligence — Admin App

Operator-only application, per **SRS v5.0, Section 5.7.2**. This is one of the
platform's two deployable applications. It is **never deployed to a public
address** (Section 18.5, 24.3) — it contains the ingestion pipeline and every
course/lecture-management capability, all of which is deliberately absent
from the Client App's codebase (the Separation Principle, Section 1.4).

```
Admin App (this repo)              Client App (separate repo — not here)
├── Ingestion pipeline             ├── Visitor-facing routes only
├── Course/lecture CRUD            ├── RAG + Answer Cache
├── Precomputation via Groq        ├── Agentic Follow-Up (Section 8.8)
├── Admin dashboard (Section 12.8) └── Public frontend
└── Never publicly reachable
        │                                   │
        └──────────── shared ───────────────┘
             PostgreSQL + pgvector, Cloudflare R2, Groq API
```

---

## 1. What you need before running this (API keys / accounts)

| # | Service | Why | Where to get it |
|---|---|---|---|
| 1 | **Groq API key** | Powers the hybrid text LLM (Llama 3.1 8B default / Llama 3.3 70B escalation) and the Vision LLM fallback — Section 8.2, 8.3 | Free at [console.groq.com/keys](https://console.groq.com/keys) |
| 2 | **Cloudflare R2** (Account ID + Access Key + Secret + bucket) | Object storage for keyframes / enhanced images / generated notes — Section 14.3 | Free at [dash.cloudflare.com](https://dash.cloudflare.com) → R2 → Create bucket → "Manage R2 API Tokens" |
| 3 | **PostgreSQL 15+ with the `pgvector` extension** | The shared lecture dataset — Section 14.1, 14.2 | Self-hosted (see below) or `docker compose up` locally for dev |
| 4 | **An admin key you choose yourself** | Defense-in-depth auth for this app (Section 17.2) | Just generate a long random string, e.g. `openssl rand -hex 32` |

Nothing else needs a paid account. faster-whisper, PaddleOCR, the embedding
model, and Real-ESRGAN all run **locally** on the same VM — no API key, no
per-call cost (Section 20.1: "production inference is via the Groq API...
which does not require the project to operate its own GPU" — that line
covers the *text* LLM; these four run as ordinary CPU inference).

---

## 2. Local setup (development)

```bash
# 1. Clone / unzip this project, then:
cd vu-admin-app
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Start a local Postgres+pgvector for development
docker compose up -d

# 3. Configure environment
cp .env.example .env
# edit .env: paste your GROQ_API_KEY, R2_* credentials, set ADMIN_API_KEY

# 4. Run database migrations (Section 14.1, 14.2)
alembic upgrade head

# 5. (Optional, only if you'll use Real-ESRGAN enhancement) download weights
mkdir -p weights
curl -L -o weights/RealESRGAN_x2plus.pth \
  https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth

# 6. Run the app — binds to 127.0.0.1 only, per Section 18.5
python admin_main.py
```

Open `http://127.0.0.1:8001` → log in with the `ADMIN_API_KEY` you set →
add a course → add a lecture → click **Process**.

The JSON API is also live at `http://127.0.0.1:8001/api/docs` (Swagger UI) —
every route there requires an `X-Admin-Key` header matching `ADMIN_API_KEY`.

---

## 3. Production deployment (Oracle Cloud Always Free — Section 14.1, 24.3)

### 3.1 Database
Install PostgreSQL 15+ and the `pgvector` extension directly on the Oracle
Always Free VM (Section 14.1 — self-hosted, not a managed free tier, because
Supabase/Render's inactivity pauses and expirations were evaluated and
rejected, Section 14.5). Then create two roles with different privilege
levels, matching Section 13.13's ownership split:

```sql
-- Admin App role: full read/write on the lecture dataset
CREATE ROLE vu_admin WITH LOGIN PASSWORD 'CHANGE_ME';
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO vu_admin;

-- Client App role: read-only on everything the Admin App writes,
-- read/write ONLY on its own tables (created by the Client App's own
-- migrations — CachedAnswer, FollowUpSuggestion, course-scope StudyNote).
CREATE ROLE vu_client WITH LOGIN PASSWORD 'CHANGE_ME_DIFFERENTLY';
GRANT SELECT ON courses, lectures, lecture_chunks, topics, chapters,
  visual_assets, quizzes, questions TO vu_client;
GRANT SELECT, INSERT, UPDATE, DELETE ON study_notes, study_note_sources
  TO vu_client;  -- Client App writes course-scope rows here; Admin App writes lecture-scope rows
```

This database-level separation is a second, independent enforcement of the
Section 5.7 Separation Principle — even a bug in the Client App's code
cannot write to `courses` or `lectures`, because its DB role is not
*permitted* to, regardless of what the application code tries to do.

### 3.2 Running the Admin App privately — THE MOST IMPORTANT STEP

**Never** run this with `--host 0.0.0.0` on a VM with a public IP. Section
18.5 requires the Admin App be reachable only via a private network path.
Pick ONE of these:

**Option A — SSH tunnel (simplest, recommended for a solo operator):**
```bash
# On the Oracle VM:
ADMIN_APP_HOST=127.0.0.1 python admin_main.py

# On your laptop, whenever you want to use the dashboard:
ssh -L 8001:127.0.0.1:8001 you@your-oracle-vm-ip
# then open http://127.0.0.1:8001 in your own browser
```

**Option B — WireGuard/VPN**, binding `ADMIN_APP_HOST` to the VM's private
VPN interface IP instead of a public one.

**Option C — same-host only**, if the Client App's reverse proxy (e.g.
nginx) runs on the same VM: bind to `127.0.0.1` and never add an nginx
`server_name`/`location` block that forwards public traffic to port 8001.

Run it as a systemd service so it survives reboots:

```ini
# /etc/systemd/system/vu-admin.service
[Unit]
Description=VU Lecture Intelligence — Admin App
After=network.target postgresql.service

[Service]
WorkingDirectory=/opt/vu-admin-app
EnvironmentFile=/opt/vu-admin-app/.env
ExecStart=/opt/vu-admin-app/.venv/bin/python admin_main.py
Restart=on-failure
User=vu_operator

[Install]
WantedBy=multi-user.target
```

### 3.3 Ingestion pacing (Section 22.7)

Both applications share one Groq account's rate-limit budget (Section 20.7).
`MAX_LECTURES_INGESTED_PER_DAY` (default 8) is a soft guardrail — the
dashboard shows today's count vs. the cap, and the API returns HTTP 429 if
you try to exceed it without `force: true`. Spread a 45-lecture course
across roughly a week rather than ingesting it all on day one.

---

## 4. Project structure

```
admin_main.py                  Application boundary — Section 5.7.2
app/
  core/
    config.py                  Settings loaded from .env
    security.py                X-Admin-Key dependency — Section 17.2
    logging.py
  db/
    models.py                  Section 13 entities (Course...ModelUsageLog)
    session.py                 Async SQLAlchemy engine/session
  routers/
    courses_admin.py           Section 4.2 — course CRUD
    lectures_admin.py          Section 4.2 — lecture CRUD
    ingestion_admin.py         Section 15.5 — trigger/monitor ingestion
    dashboard.py                Section 12.8 — server-rendered admin UI
  services/
    course_service.py          Section 15.2
    lecture_service.py         Section 15.2
    ingestion_service.py       Section 15.2 — pacing guardrail, Section 22.7
    precompute_service.py      Section 9.5 — chapters/quiz/notes via Groq
  ai_clients/
    whisper_pipeline.py        Section 8.4 — faster-whisper
    ocr_pipeline.py            Section 8.6 — PaddleOCR
    vision_llm_client.py       Section 8.3 — selective Vision LLM
    groq_client.py             Section 8.2 — hybrid 8B/70B routing (SHARED with Client App)
    embedding_model.py         Section 8.5 — local embeddings (SHARED with Client App)
    esrgan_pipeline.py         Section 8.7 — optional enhancement
  ingestion/
    pipeline.py                Section 9 — full orchestrator
    keyframe_selector.py       Section 9.2
    uncertainty_handler.py     Section 9.3
    status_tracker.py          Section 15.5
  workers/
    worker_queue.py            Section 15.3 — async dispatcher + retries (15.6)
    transcription_worker.py, ocr_worker.py, vision_worker.py,
    embedding_worker.py, llm_worker.py, enhancement_worker.py
                                Section 15.3 — standalone-callable per-stage
                                wrappers (see worker_queue.py's module
                                docstring for why they're thin today and how
                                to split them into real separate processes
                                if ingestion volume ever needs it)
  storage/
    r2_client.py                Section 14.3 — Cloudflare R2
  templates/                    Jinja2 templates for the dashboard (Section 12.8)
alembic/                        Database migrations (Section 14.1)
docker-compose.yml               Local Postgres+pgvector for development only
```

---

## 5. What this app does NOT contain (by design, Section 5.7.3)

No route, service, or module in this repository can serve a visitor-facing
request, answer a question, generate a quiz on demand, or apply the Answer
Cache (Section 10.5) — that is 100% the Client App's job, in a separate
codebase, deployed separately. This is intentional: if this repository were
ever accidentally deployed publicly, there is nothing here a visitor could
use to make it answer their question — only course/lecture management and
ingestion, gated behind the admin key.

If you're building the Client App next, it needs its own repository,
its own `client_main.py`, its own read-only DB role (`vu_client`, see
Section 3.1 above), and imports of `groq_client.py` / `embedding_model.py`
as a **shared internal package** (Section 15.1) — copy those two files (or
publish them as a small internal pip package) rather than importing this
whole Admin App into it.
