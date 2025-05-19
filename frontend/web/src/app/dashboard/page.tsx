'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Container, Box, Typography, Button } from '@mui/material';
import TransactionList from '@/components/TransactionList';
import { checkAuth, logoutUser } from '@/services/apiService';

export default function Dashboard() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const handleAuth = async () => {
      try { 
        if (!(await checkAuth())) {
          router.push('/login');
        }
      } catch (error) {
        console.error('Auth check failed:', error);
        router.push('/login');
      } finally {
        setIsLoading(false);
      }
    };

    handleAuth();
  }, [router]);

  const handleLogout = async () => {
    try {
      await logoutUser();
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