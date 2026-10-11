# Decisions

Architecture decisions for the Plaid sync pipeline. Each entry records what was chosen, what else was considered, and why. Scale context for all of these: one user, 4 Plaid Items, a handful of syncs per day.

---

## 001. SQLite to PostgreSQL 18

**Date:** 2026-10-07

**Context:** The app was on SQLite (despite psycopg2 being installed). The planned job queue and the race-condition exercise need real row-level locking and concurrent writers.

**Options considered:**
- Official `postgres` image in Docker Compose
- Postgres installed directly in WSL
- Managed cloud Postgres (Neon, Supabase)

**Chosen:** Official `postgres:18` image in Compose, data in a named volume.

**Why:** SQLite has no `SELECT ... FOR UPDATE SKIP LOCKED` and handles concurrent writers poorly. Running Postgres in Compose keeps the whole stack reproducible from one file and lets fault-injection exercises kill or restart the database directly. Cloud Postgres would put the network in the way of those exercises.

**Tradeoffs accepted:** Old data in `db.sqlite3` was not migrated (kept for reference). The data volume is tied to major version 18; upgrading later needs a dump and restore. No backups yet.

---

## 002. Podman to Docker

**Date:** 2026-10-07

**Context:** Podman was used because of restrictions on a work machine. Development is now on a personal machine only.

**Options considered:**
- Podman with `podman-compose`
- Docker Desktop with WSL integration
- Docker Engine installed directly in Ubuntu

**Chosen:** Docker Desktop with WSL integration.

**Why:** The work-machine restriction no longer applies. Docker's Compose is the reference implementation, so features like `depends_on: condition: service_healthy` behave as documented, and Podman's compose layer had already caused setup problems. The Makefile and most documentation assume Docker.

**Tradeoffs accepted:** Gives up Podman's rootless, daemonless model, which nothing in this project depends on. Docker Desktop is heavier than Engine alone.

---

## 003. Sync job granularity: one job per Plaid Item

**Date:** 2026-10-08

**Context:** A "sync" click covers 4 Plaid Items (4 separate bank logins). The job record needs a unit of work.

**Options considered:**
- One job per click (covers all 4 Items)
- One job per Item (a click creates 4 jobs)
- One job per account

**Chosen:** One job per Item.

**Why:** Each bank can succeed, fail, and retry independently, so one bank needing re-login does not fail the others. It matches the data model: the sync cursor is stored per access token, which is per Item. It also gives a natural concurrency rule (at most one running job per Item), which is what prevents two syncs racing on the same cursor. Per-account does not fit because Plaid syncs and checkpoints a whole Item, not individual accounts.

**Tradeoffs accepted:** One click creates 4 rows. Grouping the jobs from one click needs a shared identifier (later the correlation ID).

---

## 004. The SyncJob table is also the queue

**Date:** 2026-10-08

**Context:** Jobs need to be dispatched to a background worker. The question is whether the job table itself is the queue, or a separate broker dispatches jobs.

**Options considered:**
- Table as queue: the worker claims the oldest `queued` row with `SELECT ... FOR UPDATE SKIP LOCKED`
- Table as record only, Celery + Redis as the queue

**Chosen:** Table as queue.

**Why:** One source of truth: a job's row status is its real state. Celery + Redis would add a second source of truth and two failure modes to handle (a row says `queued` but the Redis message was lost; the message arrives before the row's transaction commits). At this scale, polling a table costs nothing, and having no broker makes the fault-injection exercises easier to reason about.

**Tradeoffs accepted:** No built-in retry scheduling, periodic tasks, or monitoring UI; those get built (retry/backoff in milestone 3). Table polling would become a cost at high throughput, which does not apply here. Less resume keyword recognition than Celery.

---

## 005. A real PlaidItem model

**Date:** 2026-10-08

**Context:** Per-Item jobs need something to reference, but Items only existed implicitly: the `access_token` string was repeated on every `Account` row and on `Cursor`.

**Options considered:**
- New `PlaidItem` model (item ID, access token, institution, cursor). `Account` and `SyncJob` reference it by foreign key; `Cursor` is folded into it.
- Reuse `Cursor` as the Item and point `SyncJob` at it
- Store the `access_token` string directly on each `SyncJob`

**Chosen:** New `PlaidItem` model.

**Why:** It makes the schema match the real structure (a user has Items, an Item has accounts and a cursor), which keeps the sync logic simple to follow and harder to get wrong. The access token is stored once instead of on every account and job. "At most one running job per Item" becomes a constraint on a foreign key instead of a comparison of token strings. The switch to a fresh Postgres database means there is no existing data to migrate, only models.

**Tradeoffs accepted:** Bigger change up front: `Account`, `Cursor`, and every place that reads `access_token` from an account have to change. The access token is still stored in plaintext in the database.

---

## 006. SyncJob fields

**Date:** 2026-10-08

**Context:** Deciding what a job row records, based on what would be needed to understand a failure after the fact.

**Chosen:**
- `plaid_item`: which Plaid Item the job syncs
- `status`: lifecycle only (`queued`, `in_progress`, `completed`, `failed`)
- `step`: what the job was doing (`fetch_transactions` or `update_db`), stored as fixed choices so a typo can't split the data
- `error_code`: Plaid's error code, when the failure came from Plaid
- `error_message`: any exception message, including bugs in our own code where there is no Plaid error code
- `created_at`, `started_at`, `completed_at`: time spent queued, time spent running, and detection of jobs stuck in `in_progress`. `started_at` is empty until the worker claims the job.
- `attempt_number`: which attempt this is
- Counts of added, modified, and removed transactions

**Counts on failure (added 2026-10-11):** a failed job still records the added/modified/removed counts from pages that committed before the failure, so the row shows what the sync actually accomplished, not only what successful syncs accomplished.

**Considered and left out for now:** what triggered the job (manual or scheduled). All syncs currently go through the same path, so it adds nothing yet. It becomes relevant once scheduled syncs exist and is cheap to add later.

**Why status and step are separate:** A paginated sync loops through fetch and write many times. As statuses, those would flip back and forth constantly; as a separate step field, they record where a job was without muddying its lifecycle.

---

## 007. Worker: a hand-written polling loop

**Date:** 2026-10-10

**Context:** Something has to claim queued `SyncJob` rows and run them in the background.

**Options considered:**
- A library with its own Postgres-backed queue (e.g. Procrastinate)
- A hand-written polling loop as a Django management command, claiming jobs with `SELECT ... FOR UPDATE SKIP LOCKED`
- Django's built-in tasks framework (Django 6.0+, plus a separate database backend package)

**Chosen:** Hand-written polling loop (`manage.py run_worker`).

**Why:** It uses the `SyncJob` table as the queue exactly as decision 004 describes, so no earlier decision changes. Both library options keep their own job tables, which would turn `SyncJob` back into a record and reintroduce two sources of truth. Every line of the claim and run logic is explainable.

**Tradeoffs accepted:** More code to own than a library: polling interval, graceful shutdown, and crash recovery are all hand-built. Polling adds up to one poll interval of latency before a job starts (no `LISTEN/NOTIFY` wake-up). The worker does not auto-reload on code changes like `runserver`; it must be restarted.

---

## 008. One active job per Item, enforced by a partial unique constraint

**Date:** 2026-10-10

**Context:** Two syncs for the same Item at once would race on the same cursor (see 003). Something has to prevent two active jobs per Item.

**Options considered:**
- Allow duplicate queued jobs; have the claim query skip Items that already have a job in progress
- Partial unique constraint: at most one row per Item where status is `queued` or `in_progress`
- Check in application code before creating a job

**Chosen:** Partial unique constraint (`one_active_job_per_item`).

**Why:** The database enforces the rule, so it holds even for two simultaneous requests and for any future code path that creates jobs. It keeps the job table as both the queue and the enforcer. The application-code check has a check-then-act race; the claim-time option still runs redundant syncs.

**Tradeoffs accepted:** Enqueue code must catch the constraint violation (inside a savepoint) and return the existing job. A sync requested while one is running is absorbed by the running job rather than queued after it, so changes that land mid-sync wait for the next sync.

---

## 009. Worker runs as its own Compose service

**Date:** 2026-10-10

**Context:** The worker process has to run somewhere alongside the API.

**Options considered:**
- Inside the existing backend container, alongside `runserver`
- As a separate Compose service built from the same image

**Chosen:** Separate `worker` service.

**Why:** The worker can be stopped, restarted, or killed independently of the API, which the fault-injection exercise needs. `docker compose up --scale worker=2` gives multiple workers for the race test. No process supervisor is needed inside a container.

**Tradeoffs accepted:** One more service to run. Backend and worker are built separately and can drift if only one is rebuilt.

---

## 010. Retry policy: allowlist of transient errors

**Date:** 2026-10-11

**Context:** Some sync failures resolve on their own (rate limits, bank outages, network blips); others never will (expired login, our own bugs). Retrying a permanent error wastes calls and can make things worse.

**Options considered:**
- Denylist: retry everything except known-permanent errors
- Allowlist: retry only known-transient errors; everything else fails immediately

**Chosen:** Allowlist.

**Why:** An error that has never been seen before should not be retried blindly. Bugs in our own code surface on the first failure instead of after every retry is exhausted. Unknown errors are still recorded with their code, so a transient one can be added to the list once it is understood.

**Retryable:** `RATE_LIMIT_EXCEEDED`, `INSTITUTION_DOWN`, `INSTITUTION_NOT_RESPONDING`, `INTERNAL_SERVER_ERROR`, `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION`, and network-level failures (timeouts, dropped connections), which arrive as Python exception types rather than Plaid error codes.

**Not retryable:** `ITEM_LOGIN_REQUIRED`, `INVALID_ACCESS_TOKEN`, bugs in our code, and deterministic database errors such as constraint violations.

**Tradeoffs accepted:** A transient error not on the list fails permanently the first time it appears. Retrying `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION` currently resumes from the last committed cursor, while Plaid says to restart from the cursor before the first page; per-page commits make that impossible until milestone 4.

---

## 011. Retries re-queue the same job; each attempt gets its own row

**Date:** 2026-10-11

**Context:** A retried job needs a representation that keeps a stable identity for the sync while preserving what happened on each attempt.

**Options considered:**
- A new `SyncJob` row per attempt, linked to the previous one
- One `SyncJob` per sync plus a `SyncAttempt` row per attempt
- Re-queue the same `SyncJob` row and overwrite its error each time

**Chosen:** One `SyncJob` per sync, re-queued on retry, plus a `SyncAttempt` row per attempt.

**Why:** The job keeps one ID for its whole life, so the status endpoint follows a single row, and the job stays active between attempts, so the one-active-job constraint (008) keeps working unchanged. Every attempt's timing, step, and error is preserved instead of being overwritten, which matters for debugging and for the fault-injection write-up.

**Ownership, to avoid two sources of truth:** each `SyncAttempt` owns its own timing, step, outcome, and error. The `SyncJob` owns the overall status, the current attempt number, and the final outcome.

**Tradeoffs accepted:** A second model and an extra write per attempt. Job and attempt rows must be updated consistently.

---

## 012. Retry delay enforced by a `run_after` time on the job

**Date:** 2026-10-11

**Context:** A retried job must not run again until its backoff delay has passed.

**Options considered:**
- The worker sleeps in-process for the delay, then retries
- A `run_after` field on the job; the claim query skips jobs whose time has not come

**Chosen:** `run_after`.

**Why:** A scheduled retry is stored in the database, so it survives a worker restart. The worker stays free to run other jobs while one waits.

**Tradeoffs accepted:** A migration and a change to the claim query. While a job waits for its retry it is still `queued`, so it counts as active, and a manual sync during the wait returns the waiting job instead of syncing immediately.

---

## 013. Backoff parameters

**Date:** 2026-10-11

**Chosen:**
- Base delay: 15 seconds
- Multiplier: 2x per attempt
- Maximum delay: 10 minutes (a safety cap; not reached with the current attempt limit)
- Maximum attempts: 7
- Jitter: +/-20% on each delay

**Resulting schedule:** waits of about 15s, 30s, 1m, 2m, 4m, 8m between attempts, so a job that keeps hitting retryable errors fails permanently after roughly 16 minutes (13 to 19 minutes with jitter).

**Why:** Plaid rate limits and bank outages typically clear within minutes, which this window covers without retrying for an hour. Jitter exists to keep many clients from retrying in lockstep; with one user and 4 Items that problem barely exists here, so +/-20% was chosen over full jitter to keep delays predictable in logs and tests while still demonstrating the technique.

**Tradeoffs accepted:** An outage longer than about 16 minutes fails the job; the next manual or scheduled sync picks it up. A job waiting on a retry blocks new syncs for its Item for up to that long (see 012).
