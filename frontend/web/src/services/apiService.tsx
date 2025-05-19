const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function getCSRFTokenFromCookie() {
    const name = 'csrftoken=';
    const cookies = document.cookie.split(';');
    console.log(cookies);
    for (let cookie of cookies) {
      cookie = cookie.trim();
      if (cookie.startsWith(name)) {
        return cookie.substring(name.length);
      }
    }
    return null;
  }

// Helper function to get CSRF token
export const getCsrfToken = async () => {
    console.log("LAMOAIWEMOIAMFAOWIEFMAWOIFMAWOIFMAWOIEFMAWOIEFM"+ apiUrl);
    const csrfTokenFromCookie = getCSRFTokenFromCookie();
    if (csrfTokenFromCookie) {
        return csrfTokenFromCookie;
    }

    // If CSRF token is not in cookies, fetch it from the server
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

export const getLinkToken = async () => {
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/create_link_token/`, {
    method: 'GET',
    credentials: 'include',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken,
    },
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
    console.log("LAMOAIWEMOIAMFAOWIEFMAWOIFMAWOIFMAWOIEFMAWOIEFM"+ apiUrl);
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
    console.log("LAMOAIWEMOIAMFAOWIEFMAWOIFMAWOIFMAWOIEFMAWOIEFM"+ apiUrl);
    console.log('Checking if user has accounts...');
    const csrfToken = await getCsrfToken();
    console.log(csrfToken);
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
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/get_transactions/`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
    });
    
    if (!response.ok) {
        throw new Error('Failed to fetch transactions');
    }
    
    const data = await response.json();
    return data.transactions;
}

export const getAccounts = async () => {
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/get_accounts/`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
        },
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

export const loginUser = async (username: string, password: string) => {
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/auth/login/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({ username, password }),
        credentials: 'include',
    });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.error || 'Login failed');
    }
}

export const registerUser = async (username: string, email: string, password: string) => {
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/auth/register/`, {
            method: 'POST',
            headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify({
            username: username,
            email: email || undefined, // Only send if not empty
            password: password,
            }),
            credentials: 'include',
        });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.error || 'Registration failed');
    }
}

export const checkAuth = async () => {
    console.log("This is called link: "+ `${apiUrl}/api/auth/check`);
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/auth/check/`, {
        credentials: 'include',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
        },
    });
    if (!response.ok) {
        return false;
    }
    const data = await response.json();
    return data.isAuthenticated;
}

export const forceTransactionSync = async () => {
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/force_transaction_sync/`, {
        method: 'GET',
        credentials: 'include',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
        },
    });

    if (!response.ok) {
        throw new Error('Failed to sync transactions');
    }
}

export const editTransaction = async (transactionId: string, new_name: string, new_amount: string, new_category: string) => {
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/edit_transaction/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({ 
            transaction_id: transactionId, 
            new_name: new_name, 
            new_amount: new_amount, 
            new_category: new_category
        }),
    });

    if (!response.ok) {
        throw new Error('Failed to edit transaction');
    }

    console.log(response);
}

export const deleteTransaction = async (transactionId: string) => {
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/delete_transaction/`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({ transaction_id: transactionId }),
    });

    if (!response.ok) {
        throw new Error('Failed to delete transaction');
    }
}

export const logoutUser = async () => {
    const csrfToken = await getCsrfToken();
    const response = await fetch(`${apiUrl}/api/auth/logout/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
    });

    if (!response.ok) {
        throw new Error('Logout failed');
    }
}