import { useCallback, useEffect, useRef, useState } from 'react';
import { forceTransactionSync, getSyncStatus, SyncStatus } from '@/services/apiService';

const POLL_FAST_MS = 3_000;
const POLL_SLOW_MS = 30_000;
const POLL_IDLE_MS = 5 * 60_000;
// Syncs normally finish in seconds; a job still active after this is likely
// waiting out a retry backoff, so stop hammering the endpoint.
const FAST_POLL_WINDOW_MS = 60_000;

// A stuck job has no live worker, so polling won't see it finish.
export const isSyncBusy = (status: SyncStatus | null) =>
  !!status?.items.some(item => item.current_job && item.reason !== 'job_stuck');

/**
 * Loads /api/sync_status/, polling actively queued work frequently and checking
 * occasionally while idle so scheduled syncs appear without a page reload.
 * Calls onSyncFinished when jobs go from active to done, so callers can refetch data.
 */
export function useSyncStatus(onSyncFinished: () => void) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRequesting, setIsRequesting] = useState(false);
  // Bumped after every load attempt so polling continues even when a load fails.
  const [loadCount, setLoadCount] = useState(0);

  const wasBusy = useRef(false);
  const busySince = useRef<number | null>(null);
  const onSyncFinishedRef = useRef(onSyncFinished);
  onSyncFinishedRef.current = onSyncFinished;

  const load = useCallback(async () => {
    try {
      const next = await getSyncStatus();
      const busy = isSyncBusy(next);
      if (wasBusy.current && !busy) {
        onSyncFinishedRef.current();
      }
      wasBusy.current = busy;
      setStatus(next);
      setError(null);
    } catch (err) {
      console.error('Failed to load sync status:', err);
      setError('Could not load sync status.');
    } finally {
      setLoadCount(n => n + 1);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Chained timeouts rather than setInterval: the next request starts only after
  // the previous one finished, so slow responses never overlap.
  useEffect(() => {
    if (!wasBusy.current) {
      busySince.current = null;
      const timer = setTimeout(load, POLL_IDLE_MS);
      return () => clearTimeout(timer);
    }
    busySince.current ??= Date.now();
    const delay = Date.now() - busySince.current > FAST_POLL_WINDOW_MS ? POLL_SLOW_MS : POLL_FAST_MS;
    const timer = setTimeout(load, delay);
    return () => clearTimeout(timer);
  }, [loadCount, load]);

  const refresh = useCallback(async () => {
    setIsRequesting(true);
    try {
      await forceTransactionSync();
      // Treat as busy even if the job finishes before our next poll, so we still refetch.
      wasBusy.current = true;
      busySince.current = null;
      await load();
    } catch (err) {
      console.error('Failed to queue sync:', err);
      setError('Could not start a sync. Please try again.');
    } finally {
      setIsRequesting(false);
    }
  }, [load]);

  return { status, error, isSyncing: isRequesting || isSyncBusy(status), refresh };
}
