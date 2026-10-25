'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Container, Box, Typography, Button, Alert, CircularProgress } from '@mui/material';
import TransactionList from '@/components/TransactionList';
import SyncStatusPanel from '@/components/SyncStatusPanel';
import { useSyncStatus } from '@/hooks/useSyncStatus';
import { checkAuth, logoutUser } from '@/services/apiService';

// Mounted only after the auth check passes, so its data requests never run logged out.
function DashboardContent({ onAddAccount }: { onAddAccount: () => void }) {
  // Bumped when a sync finishes, telling TransactionList to refetch.
  const [transactionsVersion, setTransactionsVersion] = useState(0);
  const sync = useSyncStatus(() => setTransactionsVersion(v => v + 1));

  return (
    <>
      <SyncStatusPanel
        status={sync.status}
        error={sync.error}
        isSyncing={sync.isSyncing}
        onRefresh={sync.refresh}
      />
      <TransactionList
        reloadKey={transactionsVersion}
        isSyncing={sync.isSyncing}
        onAddAccount={onAddAccount}
      />
    </>
  );
}

export default function Dashboard() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authAttempt, setAuthAttempt] = useState(0);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const handleAuth = async () => {
      setIsLoading(true);
      setAuthError(null);
      try {
        if (!(await checkAuth())) {
          router.replace('/login');
          return;
        }
        if (!cancelled) {
          // Only render (and fetch data) once we know the user is logged in.
          setIsLoading(false);
        }
      } catch (error) {
        if (!cancelled) {
          console.error('Auth check failed:', error);
          setAuthError('Could not verify your session. Check your connection and try again.');
          setIsLoading(false);
        }
      }
    };

    void handleAuth();
    return () => {
      cancelled = true;
    };
  }, [authAttempt, router]);

  const handleLogout = async () => {
    try {
      await logoutUser();
      router.replace('/login');
    } catch (error) {
      console.error('Logout failed:', error);
      setLogoutError('Logout failed. Please try again.');
    }
  };

  const handleAddAccount = () => {
    router.push('/link');
  };

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (authError) {
    return (
      <Container maxWidth="sm" sx={{ mt: 4 }}>
        <Alert
          severity="error"
          action={
            <Button color="inherit" size="small" onClick={() => setAuthAttempt(value => value + 1)}>
              Retry
            </Button>
          }
        >
          {authError}
        </Alert>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg">
      <Box sx={{ my: 4 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 2, mb: 4, flexWrap: 'wrap' }}>
          <Typography variant="h4" component="h1">
            Personal Finance Dashboard
          </Typography>
          <Button variant="outlined" onClick={handleLogout}>
            Logout
          </Button>
        </Box>
        {logoutError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {logoutError}
          </Alert>
        )}
        <DashboardContent onAddAccount={handleAddAccount} />
      </Box>
    </Container>
  );
} 