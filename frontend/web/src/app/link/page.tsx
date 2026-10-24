'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Container, Box, Typography, Button, CircularProgress, Alert } from '@mui/material';
import { usePlaidLink, PlaidLinkOnExit, PlaidLinkOnSuccess } from 'react-plaid-link';
import { checkAuth, exchangePublicToken, getLinkToken, getSyncStatus } from '@/services/apiService';

export default function LinkPage() {
  const router = useRouter();
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [initFailed, setInitFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  useEffect(() => {
    const init = async () => {
      try {
        // Check auth first so a logged-out user is redirected instead of seeing a link-token error.
        if (!(await checkAuth())) {
          router.replace('/login');
          return;
        }
        setLinkToken(await getLinkToken());
        setIsLoading(false);
      } catch (error) {
        console.error('Failed to create link token:', error);
        setInitFailed(true);
        setIsLoading(false);
      }
    };

    init();
  }, [router]);

  const goToDashboard = async () => {
    try {
      const { items } = await getSyncStatus();
      if (items.length > 0) {
        router.push('/dashboard');
      } else {
        setWarning('Please connect an account first.');
      }
    } catch (error) {
      console.error('Error checking linked accounts:', error);
      setError('Could not check your linked accounts. Please try again.');
    }
  };

  const onSuccess: PlaidLinkOnSuccess = async (public_token, metadata) => {
    try {
      setIsProcessing(true);
      setError(null);
      // Returns 202 once the Item is saved; the dashboard shows the first sync's progress.
      // The bank's name only reaches us here, so pass it along for display.
      await exchangePublicToken(public_token, metadata.institution?.name ?? null);
      router.push('/dashboard');
    } catch (error) {
      console.error('Failed to exchange public token:', error);
      setError('Failed to connect bank account. Please try again.');
      setIsProcessing(false);
    }
  };

  const onExit: PlaidLinkOnExit = (plaidError) => {
    // plaidError is null when the user simply closed Plaid Link.
    if (plaidError) {
      setError(plaidError.display_message || plaidError.error_message || 'Bank connection was interrupted.');
    }
  };

  const { open, ready } = usePlaidLink({ token: linkToken, onSuccess, onExit });

  if (isLoading || isProcessing) {
    return (
      <Container maxWidth="sm">
        <Box sx={{ my: 4, textAlign: 'center' }}>
          <CircularProgress />
          {isProcessing && (
            <Typography sx={{ mt: 2 }}>
              Connecting your account...
            </Typography>
          )}
        </Box>
      </Container>
    );
  }

  if (initFailed) {
    return (
      <Container maxWidth="sm">
        <Box sx={{ my: 4, textAlign: 'center' }}>
          <Typography color="error" gutterBottom>
            Failed to initialize bank connection
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
        <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center' }}>
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
      </Box>
    </Container>
  );
}
