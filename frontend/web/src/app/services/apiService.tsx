

const apiUrl = process.env.REACT_APP_API_HOST || 'http://localhost:8000';

// TODO - Add a new function to do step one for plaid
export const getLinkToken = async () => {
  const response = await fetch(`${apiUrl}/api/create_link_token/`, {
    method: 'GET',
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
    const response = await fetch(`${apiUrl}/api/exchange_public_token/`, {
        method: 'POST',
        headers: {
        'Content-Type': 'application/json',
        },
        body: JSON.stringify({ public_token: publicToken }),
    });
    
    if (!response.ok) {
        // Handle errors if the request fails (e.g., 4xx or 5xx response)
        throw new Error('Failed to exchange public token');
    }
    
    const data = await response.json();
    return data;
}