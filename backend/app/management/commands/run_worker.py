import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from app.jobs import claim_next_job, run_job


class Command(BaseCommand):
    help = "Run the sync worker: claim queued SyncJobs and process them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=2.0,
            help="Seconds to sleep when the queue is empty.",
        )

    def handle(self, *args, **options):
        poll_interval = options["poll_interval"]
        self._stopping = False

        # docker compose stop sends SIGTERM. Finish the current job, then exit.
        signal.signal(signal.SIGTERM, self._request_stop)
        signal.signal(signal.SIGINT, self._request_stop)

        self.stdout.write(f"Worker started (poll interval {poll_interval}s)")
        while not self._stopping:
            # Long-running process: drop DB connections that have gone stale.
            close_old_connections()

            job = claim_next_job()
            if job is None:
                time.sleep(poll_interval)
                continue

            self.stdout.write(f"Claimed job {job.id} for item {job.plaid_item_id}")
            run_job(job)
            job.refresh_from_db(fields=["status", "error_code", "attempt_number"])
            if job.status == job.Status.FAILED:
                self.stdout.write(f"Job {job.id} failed: {job.error_code}")
            elif job.status == job.Status.QUEUED:
                self.stdout.write(f"Job {job.id} retry scheduled (attempt {job.attempt_number})")
            else:
                self.stdout.write(f"Job {job.id} completed")

        self.stdout.write("Worker stopped")

    def _request_stop(self, signum, frame):
        self.stdout.write("Shutdown requested; finishing current job")
        self._stopping = True
