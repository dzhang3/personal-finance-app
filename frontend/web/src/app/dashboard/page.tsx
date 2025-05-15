'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Container, Box, Typography, Button } from '@mui/material';
import TransactionList from '@/components/TransactionList';

export default function Dashboard() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/auth/check/', {
          credentials: 'include',
        });

        if (!response.ok) {
          router.push('/login');
          return;
        }

        const data = await response.json();
        if (!data.isAuthenticated) {
          router.push('/login');
        }
      } catch (error) {
        console.error('Auth check failed:', error);
        router.push('/login');
      } finally {
        setIsLoading(false);
      }
    };

    checkAuth();
  }, [router]);

  const handleLogout = async () => {
    try {
      const csrfResponse = await fetch('http://localhost:8000/api/auth/csrf/', {
        method: 'GET',
        credentials: 'include',
      });
      const { csrfToken } = await csrfResponse.json();

      await fetch('http://localhost:8000/api/auth/logout/', {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
      });

      router.push('/login');
    } catch (error) {
      console.error('Logout failed:', error);
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
        <TransactionList onAddAccount={handleAddAccount} />
      </Box>
    </Container>
  );
} 