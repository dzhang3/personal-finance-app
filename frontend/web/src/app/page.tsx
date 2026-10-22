"use client";

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { CircularProgress, Box } from '@mui/material';
import { checkAuth, getSyncStatus } from '@/services/apiService';

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const handleAuth = async () => {
      try {
        if (!(await checkAuth())) {
          router.replace('/login');
          return;
        }
        // A linked Item exists as soon as the token exchange returns, even before
        // its first sync creates any accounts, so route on items rather than accounts.
        const { items } = await getSyncStatus();
        router.replace(items.length > 0 ? '/dashboard' : '/link');
      } catch (error) {
        console.error('Auth check failed:', error);
        router.replace('/login');
      }
    };

    handleAuth();
  }, [router]);

  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
      }}
    >
      <CircularProgress />
    </Box>
  );
}
