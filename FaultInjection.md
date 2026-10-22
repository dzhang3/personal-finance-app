# Fault injection: killed, raced, and frozen workers

Personal project, run locally in Docker Compose against Plaid Sandbox. One user's
data, a handful of linked Items, one worker in normal operation (two for the race
and freeze tests). Timestamps are from the worker logs; times are EDT unless marked UTC.

## Summary

| Exercise | Before the fix | After the fix |
|---|---|---|
| Kill the worker mid-sync | Job stuck `in_progress` for about 31 hours; its Item silently blocked from every future sync | Reclaimed as a new attempt once its lease expired; completed with no duplicate rows |
| Two workers on one queue | Not tested | Every job claimed by exactly one worker |
| Freeze a worker mid-sync, then wake it | Not tested | A live worker took over after the lease expired; the frozen worker woke, was fenced out, and wrote nothing |
| Alert when the worker stops | Worked: Discord alert about 3 minutes after the last check-in | Unchanged |

## Setup

- **Queue:** the `SyncJob` table, claimed with `SELECT ... FOR UPDATE SKIP LOCKED`, with a partial unique index allowing at most one active (queued or in-progress) job per Item.
- **Idempotent sync:** transactions upserted on Plaid's `transaction_id`; the pagination cursor saved only after the last page. Re-running a job replays pages harmlessly.
- **Alert:** a dead-man's switch. The worker pings healthchecks.io once a minute from its main loop, between jobs; healthchecks.io posts to Discord when pings stop (1 minute period, 2 minute grace).
- **Fault window:** `FAULT_PAGE_DELAY_SECONDS=30` makes the worker sleep between page 1 and page 2 of a sync, so it can be killed or frozen at a known point: page 1 written, cursor not yet saved. Off by default.

## Exercise 1: kill the worker mid-sync (baseline, no fix)

`docker compose kill worker` (SIGKILL, no graceful shutdown) during the fault delay of job 33 on Item 1.

**Observed:**
- Job 33 stayed `in_progress`. Its attempt row had no outcome and no finish time; last step `update_db`.
- Restarting the worker did not recover it. The claim query only selected `queued` jobs, so nothing would ever pick job 33 up again.
- Item 1 was blocked: the one-active-job constraint rejected every scheduled sync and reconcile for it, and the only trace was a DEBUG-level `job_already_active` log line.
- Other Items' queued jobs waited about 6 minutes while the worker was dead, then ran normally after the restart.
- The status endpoint still reported recent syncs as healthy, since its freshness window is 12 hours.
- The Discord alert fired: "DOWN", with the last ping 3 minutes earlier (period plus grace), and "UP" after the restart.

Job 33 stayed stuck from 2026-10-20 20:30 UTC until the fix was deployed at 2026-10-22 03:18 UTC.

## The fix: leases with a fencing token

- Claiming a job sets `lease_expires_at = now + 60s`. The worker renews it at the start of every page.
- A job that is `in_progress` with an expired (or missing) lease is claimable again. The reclaim marks the abandoned attempt `lease_expired`, increments `attempt_number`, and starts a new attempt. A job abandoned 7 times fails instead of looping.
- **Fencing:** `attempt_number` is the fencing token. Renewal is a single conditional `UPDATE ... WHERE id = ? AND status = 'in_progress' AND attempt_number = ?`; zero rows updated means another worker owns the job, and the old worker raises `LeaseLost` and stops. Cursor saves, reconcile repairs, and outcome writes all run inside a transaction that starts with that renewal, so the row lock blocks a reclaim between the check and the write.

## Exercise 2: recovery of jobs abandoned before the fix

On first start of the new code (2026-10-21):

- **23:18:07:** job 33 reclaimed (`lease_expired_at=null`, a pre-lease row), run as attempt 2, completed at 23:18:36.
- **23:18:36:** job 394 (Item 5, claimed by the old code and killed) reclaimed the same way, completed at 23:19:05.
- **23:19:05 to 23:20:02:** Item 1, unblocked, received its scheduled sync (job 398) and reconcile (job 401). The reconcile found no drift.
- Duplicate check: 962 transactions, 962 distinct `transaction_id`s. Attempt 2 replayed page 1, which attempt 1 had already written, and the upsert absorbed it.

## Exercise 3: two workers racing on one queue

`docker compose up -d --scale worker=2`, then syncs queued for all Items.

Jobs 402 to 406 were split: `worker-2` ran 402, 404 and 406; `worker-1` ran 403 and 405. Every job ID appears under exactly one worker identity in the logs.

## Exercise 4: freeze a worker mid-sync (the zombie case)

Two workers running. `docker pause` on the worker holding the job: the process is frozen, not dead, like a long GC pause or a VM stall. This is the case leases alone don't solve.

- **23:33:37:** `worker-2` claims job 408 (Item 5). Lease expires at 23:34:37.8.
- **23:33:38:** page 1 written; fault delay begins; `worker-2` paused.
- **23:34:39:** `worker-1` logs `lease_expired_reclaimed` with `lease_expired_at` 23:34:37.8, about 1 second after expiry (its 2-second poll interval). It never took the job while the lease was live.
- **23:35:08:** attempt 2 replays page 1, writes page 2, saves the cursor, completes.
- **23:36:04:** `worker-2` unpaused. It resumes, tries to renew before fetching page 2, and logs `lease_lost`: "another worker reclaimed this job; stopping without writing". No cursor save and no outcome from attempt 1.
- Duplicate check after the run: 962 transactions, 962 distinct `transaction_id`s.

## Findings and limitations

- **The alert can't see one of several workers dying.** During exercise 4, healthchecks.io stayed green because `worker-1` kept pinging the same check. With multiple workers, each needs its own check. Normal operation here runs one worker.
- **Leases depend on clocks.** Expiry is computed from each worker's clock. The logs show one job whose completion was stamped 0.43 seconds before its start, most likely a clock correction in WSL2 after sleep. A clock jumping forward could make a worker reclaim a live job. Using the database's clock (`Now()` in SQL) for both setting and checking leases would give one time source.
- **Writes between renewals aren't individually fenced.** A worker that wakes in the middle of a page can still upsert that page's transactions before its next renewal. That's harmless here because the upsert is idempotent and the data comes from Plaid, but only the cursor, repairs and outcomes are strictly fenced.
- **One renewal per page assumes a page takes well under 60 seconds.** A Plaid call that hangs past the lease would hand the job to another worker; the original would then be fenced out when it returned.
- **The blocked Item was silent before the fix.** A job stuck forever produced no warning, only a DEBUG line per rejected enqueue. The status endpoint now reports it as `job_stuck`, and leases recover it.

## Reproducing

```bash
# .env next to docker-compose.yml
FAULT_PAGE_DELAY_SECONDS=30
docker compose up -d --scale worker=2

# Force a two-page sync for one Item
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "UPDATE app_plaiditem SET cursor = NULL WHERE id = 5;"'
docker compose exec backend python manage.py shell -c "from app.models import PlaidItem; from app.jobs import enqueue_sync; print(enqueue_sync(PlaidItem.objects.get(id=5)).id)"

# When event=fault_delay appears, freeze (or kill) the worker named in that log line
docker pause app-worker-2          # or: docker compose kill worker
# ~60s later the other worker logs lease_expired_reclaimed, then job_completed
docker unpause app-worker-2        # expect lease_lost

# Clean up
# remove FAULT_PAGE_DELAY_SECONDS from .env, then:
docker compose up -d --scale worker=1
```
