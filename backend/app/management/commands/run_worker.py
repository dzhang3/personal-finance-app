import logging
import os
import signal
import socket
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from app import heartbeat
from app.jobs import claim_next_job, enqueue_due_reconciles, enqueue_due_syncs, run_job
from app.logging_utils import job_context, log_event

logger = logging.getLogger("app.worker")

# How often the worker checks whether any Item is due for a scheduled job (decisions 020, 026).
SCHEDULE_CHECK_SECONDS = 60


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
        self._stop_signal = None

        # docker compose stop sends SIGTERM. Finish the current job, then exit.
        signal.signal(signal.SIGTERM, self._request_stop)
        signal.signal(signal.SIGINT, self._request_stop)

        # Every line from this process carries the worker's identity, so lines from
        # two workers (e.g. in a race test) can be told apart.
        with job_context(worker=f"{socket.gethostname()}:{os.getpid()}"):
            log_event(logger, "worker_started", poll_interval_s=poll_interval)
            self._loop(poll_interval)
            log_event(logger, "worker_stopped", signal=self._stop_signal)

    def _loop(self, poll_interval):
        last_schedule_check = None
        while not self._stopping:
            # Long-running process: drop DB connections that have gone stale.
            close_old_connections()

            if last_schedule_check is None or time.monotonic() - last_schedule_check >= SCHEDULE_CHECK_SECONDS:
                last_schedule_check = time.monotonic()
                # Only reached between jobs, so a job that hangs also stops the pings.
                heartbeat.ping()
                # Syncs first: if both are due, the sync takes the Item's one
                # active slot and the reconcile waits for a later check.
                syncs = enqueue_due_syncs()
                reconciles = enqueue_due_reconciles()
                if syncs or reconciles:
                    log_event(logger, "scheduled_jobs_queued", syncs=syncs, reconciles=reconciles)

            job = claim_next_job()
            if job is None:
                time.sleep(poll_interval)
                continue

            # run_job logs job_started and the outcome, with job context attached.
            run_job(job)

    def _request_stop(self, signum, frame):
        # No logging here: a signal can interrupt a log call already holding the
        # handler's lock. Just record it; handle() logs on the way out.
        self._stop_signal = signal.Signals(signum).name
        self._stopping = True
