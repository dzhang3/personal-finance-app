const apiUrl = process.env.REACT_APP_API_HOST || 'http://localhost:8000';

// Helper function to get CSRF token
const getCsrfToken = async () => {
    const response = await fetch(`${apiUrl}/api/auth/csrf/`, {
        method: 'GET',
        credentials: 'include',
    });
    if (!response.ok) {
        throw new Error('Failed to get CSRF token');
    }
    const { csrfToken } = await response.json();
    return csrfToken;
};

// TODO - Add a new function to do step one for plaid
export const getLinkToken = async () => {
  const response = await fetch(`${apiUrl}/api/create_link_token/`, {
    method: 'GET',
    credentials: 'include',
  });

  if (!response.ok) {
    // Handle errors if the request fails (e.g., 4xx or 5xx response)
    throw new Error('Failed to fetch link token');
  }

  const data = await response.json();
  console.log(data);
  return data.link_token;
}

export const exchangePublicToken = async (publicToken: string) => {
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/exchange_public_token/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({ public_token: publicToken }),
    });
    
    if (!response.ok) {
        // Handle errors if the request fails (e.g., 4xx or 5xx response)
        throw new Error('Failed to exchange public token');
    }
    
    const data = await response.json();
    return data;
}

export const checkUserExists = async () => {
    const response = await fetch(`${apiUrl}/api/check_user_exists/`, {
        method: 'GET',
    });
    
    if (!response.ok) {
        throw new Error('Failed to check if user exists');
    }
    
    const data = await response.json();
    return data.exists;
}

export const checkHasAccounts = async () => {
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/check_has_accounts/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
    });
    
    if (!response.ok) {
        throw new Error('Failed to check if user has accounts');
    }
    
    const data = await response.json();
    return data.hasAccounts;
}

export const getTransactions = async () => {
    const response = await fetch(`${apiUrl}/api/get_transactions/`, {
        method: 'GET',
        credentials: 'include',
    });
    
    if (!response.ok) {
        throw new Error('Failed to fetch transactions');
    }
    
    const data = await response.json();
    return data.transactions;
}

export const getAccounts = async () => {
    const response = await fetch(`${apiUrl}/api/get_accounts/`, {
        method: 'GET',
        credentials: 'include',
    });
    
    if (!response.ok) {
        // Handle errors if the request fails (e.g., 4xx or 5xx response)
        throw new Error('Failed to fetch accounts');
    }
    
    const data = await response.json();
    return data.accounts;
}

export const createUser = async () => {
    const response = await fetch(`${apiUrl}/api/create_user/`, {
        method: 'POST',
    });
    
    if (!response.ok) {
        throw new Error('Failed to create user');
    }
    
    const data = await response.json();
    return data.user;
}