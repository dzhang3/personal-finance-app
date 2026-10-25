"use client";

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Alert, Box, Button, CircularProgress } from '@mui/material';
import { checkAuth, getSyncStatus } from '@/services/apiService';

export default function Home() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const handleAuth = async () => {
      try {
        if (!(await checkAuth())) {
          router.replace('/login');
          return;
        }
        // A linked Item exists as soon as the token exchange returns, even before
        // its first sync creates any accounts, so route on items rather than accounts.
        const { items } = await getSyncStatus();
        if (!cancelled) {
          router.replace(items.length > 0 ? '/dashboard' : '/link');
        }
      } catch (error) {
        if (!cancelled) {
          console.error('Failed to load session or linked bank status:', error);
          setError('Could not verify your session. Check your connection and try again.');
        }
      }
    };

    void handleAuth();
    return () => {
      cancelled = true;
    };
  }, [attempt, router]);

  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
      }}
    >
      {error ? (
        <Box sx={{ width: 'min(100% - 32px, 480px)' }}>
          <Alert
            severity="error"
            action={
              <Button color="inherit" size="small" onClick={() => {
                setError(null);
                setAttempt(value => value + 1);
              }}>
                Retry
              </Button>
            }
          >
            {error}
          </Alert>
        </Box>
      ) : (
        <CircularProgress />
      )}
    </Box>
  );
}
