import { Alert, Box, Button, Chip, ChipProps, CircularProgress, Paper, Stack, Typography } from '@mui/material';
import { ItemSyncStatus, SyncStatus } from '@/services/apiService';

interface SyncStatusPanelProps {
  status: SyncStatus | null;
  error: string | null;
  isSyncing: boolean;
  onRefresh: () => void;
}

const relativeTime = new Intl.RelativeTimeFormat('en-US', { numeric: 'auto' });

const formatAgo = (isoString: string): string => {
  const minutes = Math.round((new Date(isoString).getTime() - Date.now()) / 60_000);
  if (Math.abs(minutes) < 60) return relativeTime.format(minutes, 'minute');
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 48) return relativeTime.format(hours, 'hour');
  return relativeTime.format(Math.round(hours / 24), 'day');
};

const describeItem = (item: ItemSyncStatus): { label: string; color: ChipProps['color'] } => {
  const job = item.current_job;
  if (item.reason === 'job_stuck') {
    return { label: 'Sync stalled', color: 'error' };
  }
  if (job?.status === 'in_progress') {
    return { label: 'Syncing...', color: 'info' };
  }
  if (job && job.attempt > 1) {
    return { label: `Retrying (attempt ${job.attempt})`, color: 'warning' };
  }
  if (job) {
    return { label: 'Sync queued', color: 'info' };
  }
  if (item.last_error) {
    return { label: 'Last sync failed', color: 'error' };
  }
  if (item.reason === 'never_synced') {
    return { label: 'Not synced yet', color: 'warning' };
  }
  if (item.reason === 'stale') {
    return { label: 'Out of date', color: 'warning' };
  }
  return { label: 'Up to date', color: 'success' };
};

export default function SyncStatusPanel({ status, error, isSyncing, onRefresh }: SyncStatusPanelProps) {
  return (
    <Paper elevation={2} sx={{ maxWidth: 800, mx: 'auto', p: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h6">Linked Banks</Typography>
        <Button
          variant="outlined"
          onClick={onRefresh}
          disabled={isSyncing}
          startIcon={isSyncing ? <CircularProgress size={20} /> : null}
          size="small"
        >
          {isSyncing ? 'Syncing...' : 'Sync Now'}
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      )}

      {status && status.items.length === 0 && (
        <Typography color="textSecondary">No banks linked yet.</Typography>
      )}

      <Stack spacing={1}>
        {status?.items.map((item, index) => {
          const { label, color } = describeItem(item);
          return (
            <Box key={item.item_id}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 2 }}>
                <Box>
                  <Typography variant="body1">
                    {item.institution_name ?? `Bank ${index + 1}`}
                  </Typography>
                  <Typography variant="body2" color="textSecondary">
                    {item.last_successful_sync_at
                      ? `Last synced ${formatAgo(item.last_successful_sync_at)}`
                      : 'No successful sync yet'}
                  </Typography>
                </Box>
                <Chip label={label} color={color} size="small" />
              </Box>
              {item.last_error && !item.current_job && (
                <Typography variant="body2" color="error" sx={{ mt: 0.5 }}>
                  {item.last_error.message || item.last_error.code}
                </Typography>
              )}
            </Box>
          );
        })}
      </Stack>
    </Paper>
  );
}
