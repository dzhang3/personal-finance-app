const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface Transaction {
    transaction_id: string;
    // Plaid's sign convention: positive = money out; negative = refunds, payments, income.
    amount: number;
    description: string;
    merchant_name: string | null;
    datetime: string;
    // Plaid's personal_finance_category.primary, e.g. FOOD_AND_DRINK.
    transaction_type: string;
    payment_channel: string | null;
    account: {
        name: string;
        account_type: string;
        institution: string;
    };
}

export interface BudgetTarget {
    category: string;
    monthly_limit: string;
}

export type SyncReason = 'ok' | 'job_stuck' | 'never_synced' | 'stale';

export interface SyncJob {
    id: number;
    kind: string;
    status: string;
    attempt: number;
    created_at: string;
    started_at: string | null;
    run_after: string | null;
    lease_expires_at: string | null;
}

export interface ItemSyncStatus {
    item_id: number;
    institution_name: string | null;
    healthy: boolean;
    reason: SyncReason;
    last_successful_sync_at: string | null;
    current_job: SyncJob | null;
    last_error: { code: string; message: string; at: string } | null;
}

export interface SyncStatus {
    healthy: boolean;
    checked_at: string;
    items: ItemSyncStatus[];
}

export class ApiError extends Error {
    constructor(message: string, public status: number) {
        super(message);
    }
}

function getCSRFTokenFromCookie() {
    const name = 'csrftoken=';
    for (const cookie of document.cookie.split(';')) {
        const trimmed = cookie.trim();
        if (trimmed.startsWith(name)) {
            return trimmed.substring(name.length);
        }
    }
    return null;
}

// Read fresh on every call: Django rotates the token at login.
const getCsrfToken = async (): Promise<string> => {
    const fromCookie = getCSRFTokenFromCookie();
    if (fromCookie) {
        return fromCookie;
    }
    const { csrfToken } = await request<{ csrfToken: string }>('auth/csrf/');
    return csrfToken;
};

async function request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
    const method = options.method ?? 'GET';
    const headers: Record<string, string> = {};
    // Django only checks CSRF on unsafe methods.
    if (method !== 'GET') {
        headers['X-CSRFToken'] = await getCsrfToken();
    }
    if (options.body !== undefined) {
        headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(`${apiUrl}/api/${path}`, {
        method,
        headers,
        credentials: 'include',
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });

    // Some endpoints return 202 with no body; error pages may not be JSON.
    const text = await response.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : null;
    } catch {
        data = null;
    }

    if (!response.ok) {
        throw new ApiError(data?.error || `Request failed (${response.status})`, response.status);
    }
    return data as T;
}

// --- Auth ---

export const loginUser = async (username: string, password: string) => {
    await request('auth/login/', { method: 'POST', body: { username, password } });
};

export const registerUser = async (username: string, email: string, password: string) => {
    await request('auth/register/', {
        method: 'POST',
        body: { username, email: email || undefined, password },
    });
};

export const logoutUser = async () => {
    await request('auth/logout/', { method: 'POST' });
};

export const checkAuth = async (): Promise<boolean> => {
    try {
        const data = await request<{ isAuthenticated: boolean }>('auth/check/');
        return data.isAuthenticated;
    } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
            return false;
        }
        throw err;
    }
};

// --- Plaid / sync ---

export const getLinkToken = async (): Promise<string> => {
    const data = await request<{ link_token: string }>('create_link_token/');
    return data.link_token;
};

// 202, no body: the first sync runs in the background.
export const exchangePublicToken = async (publicToken: string, institutionName: string | null) => {
    await request('exchange_public_token/', {
        method: 'POST',
        body: { public_token: publicToken, institution_name: institutionName },
    });
};

// 202, no body: only queues jobs. Poll getSyncStatus to see them finish.
export const forceTransactionSync = async () => {
    await request('force_transaction_sync/');
};

export const getSyncStatus = () => request<SyncStatus>('sync_status/');

// --- Transactions ---

export const getTransactions = async (): Promise<Transaction[]> => {
    const data = await request<{ transactions: Transaction[] }>('get_transactions/');
    return data.transactions;
};

export const getBudgetTargets = async (): Promise<BudgetTarget[]> => {
    const data = await request<{ targets: BudgetTarget[] }>('budget_targets/');
    return data.targets;
};

export const saveBudgetTarget = async (category: string, monthlyLimit: string): Promise<BudgetTarget> => {
    return request<BudgetTarget>('budget_targets/', {
        method: 'PUT',
        body: { category, monthly_limit: monthlyLimit },
    });
};

export const deleteBudgetTarget = async (category: string): Promise<void> => {
    await request<void>('budget_targets/', { method: 'DELETE', body: { category } });
};

export const editTransaction = async (transactionId: string, new_name: string, new_amount: string, new_category: string) => {
    await request('edit_transaction/', {
        method: 'POST',
        body: { transaction_id: transactionId, new_name, new_amount, new_category },
    });
};

export const deleteTransaction = async (transactionId: string) => {
    await request('delete_transaction/', { method: 'DELETE', body: { transaction_id: transactionId } });
};
