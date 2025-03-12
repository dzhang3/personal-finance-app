"use client";

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { CircularProgress, Box } from '@mui/material';

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/auth/check/', {
          credentials: 'include',
        });

        if (!response.ok) {
          // Not authenticated, redirect to login
          router.push('/login');
          return;
        }

        const data = await response.json();
        if (data.isAuthenticated) {
          // User is authenticated, check if they have accounts
          const accountsResponse = await fetch('http://localhost:8000/api/check_has_accounts/', {
            method: 'POST',
            credentials: 'include',
          });
          const accountsData = await accountsResponse.json();

          if (accountsData.hasAccounts) {
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

    checkAuth();
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
