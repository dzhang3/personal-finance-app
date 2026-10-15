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

---

## 014. Idempotency key: Plaid's `transaction_id`, unique across the table

**Date:** 2026-10-12

**Context:** The pipeline is at-least-once: retries and restarts can deliver the same Plaid page more than once. Writes must be idempotent, which needs a key that identifies "the same transaction."

**Options considered:**
- `(account, transaction_id)` unique together
- A content fingerprint (hash of date, amount, merchant, account)
- `transaction_id` alone, unique across the table

**Chosen:** `transaction_id` alone.

**Why:** Plaid documents it as the unique ID of the transaction. If that were ever wrong, the failure is loud: the unique constraint rejects the write and the job fails visibly, instead of two transactions being silently merged. A content fingerprint would collapse genuinely separate purchases (same merchant, amount, and day) and would not match a pending charge whose amount changes when it posts.

**Tradeoffs accepted:** Fully trusts an external system's ID (a natural key). Relinking the same bank produces new IDs, so that case remains a semantic duplicate for reconciliation (milestone 5), not something this key can catch.

---

## 015. Upserts via `INSERT ... ON CONFLICT DO UPDATE`

**Date:** 2026-10-12

**Options considered:**
- Delete the page's IDs, then insert fresh
- `bulk_create(update_conflicts=True, ...)`: one `INSERT ... ON CONFLICT DO UPDATE` per page
- `update_or_create` per row

**Chosen:** `bulk_create(update_conflicts=True, ...)`.

**Why:** One atomic statement per page, with the database deciding "new or existing," so there is no read-then-write race and no per-row query cost. Row identity (`id`, `created_at`) is preserved across syncs, unlike delete-and-insert.

**Tradeoffs accepted:** Requires the unique constraint from 014 and is Postgres-specific in its semantics. Applying Plaid's `modified` data overwrites manual edits made through `edit_transaction`. Accepted: Plaid's later data is treated as the newer and more correct version. If manual edits ever need to survive, they belong in separate override fields that the upsert never touches.

---

## 016. Cursor saved only after the whole sync succeeds

**Date:** 2026-10-12

**Context:** A sync spans several pages. On `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION`, Plaid requires restarting from the cursor held before the first page.

**Options considered:**
- Buffer every page in memory and commit everything once at the end
- Commit each page's data as it arrives, but save the cursor only after the last page
- Commit each page together with its cursor

**Chosen:** Commit each page's data; save the cursor only at the end.

**Why:** The cursor never advances until the whole sync succeeds, so every retry, for any reason, automatically restarts from the correct original cursor with no special restart logic, which is exactly what Plaid requires after a mutation-during-pagination error. Pages already written are replayed on retry and absorbed by the idempotent upserts (014, 015). Memory stays bounded to one page.

**Tradeoffs accepted:** Any failure re-fetches every page, not just the remaining ones. Correctness depends entirely on the upserts being idempotent, which the tests must prove.

---

## 017. Store every transaction with Plaid's sign; interpret at display time

**Date:** 2026-10-12

**Context:** The old sync dropped every transaction with `amount <= 0`. In Plaid's convention, positive means money out, so this discarded income, card payments, and refunds.

**Options considered:**
- Store only spending (`amount > 0`), as before
- Store income and spending in separate tables or with a direction flag
- Store everything as Plaid sends it, signed, and filter by category when displaying

**Chosen:** Store everything, signed.

**Why:** The sync layer should mirror Plaid faithfully; deciding what counts as spending is a reporting concern. Filtering at ingest also broke correctness on credit cards alone: refunds are negative, so dropping them overstated spending, and it made reconciliation (milestone 5) impossible because the local table could never match Plaid's.

**Tradeoffs accepted:** Spending totals must exclude card payments and transfers between my own accounts (`TRANSFER_IN`, `TRANSFER_OUT`, `LOAN_PAYMENTS`) or they double-count. Plaid bills per connected Item, not per transaction, so ingest filtering never saved fees; the only fee lever is how many Items are connected.

---

## 018. Reconcile against `/transactions/get` for a trailing window

**Date:** 2026-10-13

**Context:** The sync path is incremental, and increments drift: dropped changes, bugs, and old filters (017) leave the table different from Plaid's. Reconciliation needs a source to compare against.

**Options considered:**
- Account balances: compare Plaid's balance with what stored transactions imply
- A fresh full `/transactions/sync` from an empty cursor, diffed against the table
- `/transactions/get` for a trailing date window, diffing IDs and compared fields

**Chosen:** `/transactions/get` for a trailing window.

**Why:** It is a different endpoint from the sync path, so a blind spot in how sync delivers or parses data is not shared by the check. It produces exact lists of missing, extra, and mismatched transactions, which repair needs (019); a balance check only says that something is off, and can't even do that reliably because the starting balance, interest, and fees aren't in the table. Cost is zero: `/transactions/get` is covered by the flat Transactions fee ($0.30 per Item per month), unlike Balance ($0.10 per call) or Transactions Refresh ($0.12 per call).

**Tradeoffs accepted:** Drift older than the window isn't seen (021). `/transactions/get` pages by offset, so a transaction arriving mid-fetch can shift pages; the fetch is checked against Plaid's `total_transactions` and fails rather than reconcile against a partial list.

---

## 019. Repair drift automatically, with an audit row per change

**Date:** 2026-10-13

**Options considered:**
- Repair automatically: insert missing, overwrite mismatched, delete extra
- Report only: record the diff and let a human decide
- Repair small drift automatically; above a threshold, record and repair nothing

**Chosen:** Repair automatically. Every change is recorded in `ReconcileRepair` with before and after snapshots, in the same transaction as the change.

**Why:** With one user and a handful of Items, drift is rare and small, and manual review of every diff is effort with no payoff. Plaid is the source of truth for transaction data (015), so its version wins.

**Tradeoffs accepted:** A bug in the diff or an incomplete Plaid response could delete real rows. Mitigations: the fetch fails on a count mismatch (018), and the audit rows make any bad run traceable and reversible by hand. No threshold guard yet; the fault-injection milestone may justify one.

---

## 020. Reconcile as a scheduled job type on the existing queue

**Date:** 2026-10-13

**Options considered:**
- Its own job type, scheduled daily
- On demand from an endpoint
- Right after every successful sync, in the same job

**Chosen:** A `kind` field on `SyncJob` (`sync` or `reconcile`). The worker checks once a minute and queues a reconcile for any Item without one in the last 24 hours.

**Why:** Drift is rare and not urgent, so daily is enough. Running through the same queue reuses claiming, retries, and attempts, and the one-active-job constraint (008) guarantees a reconcile never runs concurrently with a sync on the same Item; a race between them would report false drift and could delete rows the sync just wrote.

**Tradeoffs accepted:** The schedule lives in the worker, so no reconciles happen while it's down. If a sync is active when a reconcile is due, the reconcile waits until the next check.

---

## 021. 30-day reconciliation window

**Date:** 2026-10-13

**Options considered:** 30 days, 90 days, full history.

**Chosen:** 30 days.

**Why:** Covers the period where Plaid still changes transactions (pending to posted, corrections) and where new drift appears, while keeping each run small.

**Tradeoffs accepted:** Older drift is invisible to the daily run, including the transactions the old `amount > 0` filter dropped. `reconcile_item` takes the window as a parameter, so a one-time larger run can backfill those.

---

## 022. Store Plaid's posted `date` separately from the purchase time

**Date:** 2026-10-14

**Context:** `Transaction.datetime` holds when the purchase happened (authorized time, falling back to posted), which is what spending views want. But `/transactions/get` selects its window by the posted `date`. Authorization and posting are usually 1 to 3 days apart, and a timestamp converted to a calendar day depends on the zone chosen. Windowing local rows by `datetime` would put purchases near the window edge on one side only, where auto-repair (019) would delete them as "extra."

**Options considered:**
- A separate `posted_date` column holding Plaid's `date` exactly, used for the reconcile window
- No model change: widen the local window by a margin and only treat rows well inside it as extra

**Chosen:** A separate `posted_date` column.

**Why:** Both sides of the comparison filter on the identical value, so the windows match exactly with no tuning. A margin would have to cover the authorization-to-posting gap, which varies by bank, and drift at the edges would never be repaired.

**Tradeoffs accepted:** A migration, and rows written before it have a null `posted_date` until a sync or reconcile rewrites them. The first reconcile after the migration treats those rows as missing and upserts Plaid's version over them, so its audit log shows them as inserts.
