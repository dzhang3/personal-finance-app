'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Container, Box, Typography, Button, Alert } from '@mui/material';
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
  const [logoutError, setLogoutError] = useState<string | null>(null);

  useEffect(() => {
    const handleAuth = async () => {
      try {
        if (await checkAuth()) {
          // Only render (and fetch data) once we know the user is logged in.
          setIsLoading(false);
        } else {
          router.replace('/login');
        }
      } catch (error) {
        console.error('Auth check failed:', error);
        router.replace('/login');
      }
    };

    handleAuth();
  }, [router]);

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
    return null;
  }

  return (
    <Container maxWidth="lg">
      <Box sx={{ my: 4 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 4 }}>
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