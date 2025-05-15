'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Container, Box, Typography, Button, CircularProgress, Alert } from '@mui/material';
import { usePlaidLink, PlaidLinkOptions } from 'react-plaid-link';
import { checkHasAccounts, checkAuth } from '@services';

export default function LinkPage() {
  const router = useRouter();
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  

  useEffect(() => {
    const init = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/create_link_token/', {
          credentials: 'include',
        });
        const data = await response.json();
        setLinkToken(data.link_token);
      } catch (error) {
        console.error('Failed to create link token:', error);
        setError('Failed to initialize bank connection');
      } finally {
        setIsLoading(false);
      }
    };

    init();
  }, []);

  const goToDashboard = async () => {
    try {
      const hasAccounts = await checkHasAccounts();
      if (hasAccounts) {
        router.push('/dashboard');
      } else {
        setWarning('Please connect an account first.');
      }
    } catch (error) {
      console.error('Error checking accounts:', error);
      setError('An error occurred while checking accounts.');
    }
  };

  useEffect(() => {
      const handleAuth = async () => {
        try {
          if (!(await checkAuth())) {
            router.push('/login');
          }
        } catch (error) {
          console.error('Auth check failed:', error);
          router.push('/login');
        }
      };
  
      handleAuth();
    }, [router]);

  const onSuccess = async (public_token: string) => {
    try {
      setIsProcessing(true);
      setError(null);
      
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
      setIsProcessing(false);
    }
  };

  const config: PlaidLinkOptions = {
    token: linkToken!,
    onSuccess,
  };

  const { open, ready } = usePlaidLink(config);

  if (isLoading || isProcessing) {
    return (
      <Container maxWidth="sm">
        <Box sx={{ my: 4, textAlign: 'center' }}>
          <CircularProgress />
          {isProcessing && (
            <Typography sx={{ mt: 2 }}>
              Connecting your account and fetching transactions...
            </Typography>
          )}
        </Box>
      </Container>
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
        {warning && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            {warning}
          </Alert>
        )}
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
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
        <Button
          variant="outlined"
          onClick={goToDashboard}
          size="large"
        >
          Go to Dashboard
        </Button>
      </Box>
    </Container>
  );
} 