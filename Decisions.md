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

**Considered and left out for now:** what triggered the job (manual or scheduled). All syncs currently go through the same path, so it adds nothing yet. It becomes relevant once scheduled syncs exist and is cheap to add later.

**Why status and step are separate:** A paginated sync loops through fetch and write many times. As statuses, those would flip back and forth constantly; as a separate step field, they record where a job was without muddying its lifecycle.
