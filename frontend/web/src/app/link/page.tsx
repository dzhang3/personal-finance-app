'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Container, Box, Typography, Button, CircularProgress } from '@mui/material';
import { usePlaidLink, PlaidLinkOptions } from 'react-plaid-link';

export default function LinkPage() {
  const router = useRouter();
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
          return;
        }

        // Get link token
        const linkResponse = await fetch('http://localhost:8000/api/create_link_token/', {
          credentials: 'include',
        });
        const linkData = await linkResponse.json();
        setLinkToken(linkData.link_token);
      } catch (error) {
        console.error('Auth check failed:', error);
        setError('Failed to initialize bank connection');
      } finally {
        setIsLoading(false);
      }
    };

    checkAuth();
  }, [router]);

  const onSuccess = async (public_token: string, metadata: any) => {
    try {
      const csrfResponse = await fetch('http://localhost:8000/api/auth/csrf/', {
        method: 'GET',
        credentials: 'include',
      });
      const { csrfToken } = await csrfResponse.json();

      const response = await fetch('http://localhost:8000/api/exchange_public_token/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({ public_token }),
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to exchange token');
      }

      router.push('/dashboard');
    } catch (error) {
      console.error('Failed to exchange public token:', error);
      setError('Failed to connect bank account');
    }
  };

  const config: PlaidLinkOptions = {
    token: linkToken!,
    onSuccess,
  };

  const { open, ready } = usePlaidLink(config);

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Container maxWidth="sm">
        <Box sx={{ my: 4, textAlign: 'center' }}>
          <Typography color="error" gutterBottom>
            {error}
          </Typography>
          <Button 
            variant="contained" 
            onClick={() => window.location.reload()}
            sx={{ mt: 2 }}
          >
            Retry
          </Button>
        </Box>
      </Container>
    );
  }

  return (
    <Container maxWidth="sm">
      <Box sx={{ my: 4, textAlign: 'center' }}>
        <Typography variant="h4" component="h1" gutterBottom>
          Connect Your Bank Account
        </Typography>
        <Typography variant="body1" sx={{ mb: 4 }}>
          To get started, connect your bank account using our secure integration with Plaid.
        </Typography>
        <Button
          variant="contained"
          onClick={() => open()}
          disabled={!ready}
          size="large"
        >
          Connect Bank Account
        </Button>
      </Box>
    </Container>
  );
} 