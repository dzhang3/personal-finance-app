"use client";

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { CircularProgress, Box } from '@mui/material';
import { checkHasAccounts, checkAuth } from '@services';

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const handleAuth = async () => {
      try {
        if (await checkAuth()) {
          // Check if the user has linked accounts
          console.log('calling checkHasAccounts');
          const hasAccounts = await checkHasAccounts();
          if (hasAccounts) {
            router.push('/dashboard'); // Or wherever your main app page is
          } else {
            router.push('/link'); // Or wherever your Plaid link page is
          }
        } else {
          router.push('/login');
        }
      } catch (error) {
        console.error('Auth check failed:', error);
        router.push('/login');
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
