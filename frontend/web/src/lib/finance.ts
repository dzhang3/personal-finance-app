import { Transaction } from '@/services/apiService';

// Money moving between your own accounts, paying down debt, or coming in: not spending.
export const NON_SPENDING_CATEGORIES = new Set(['TRANSFER_IN', 'TRANSFER_OUT', 'LOAN_PAYMENTS', 'INCOME']);

export interface SpendingSummary {
  total: number;
  categories: { name: string; value: number }[];
}

/**
 * Net spending per category. Amounts follow Plaid's sign convention (positive =
 * money out), so a refund (negative) reduces its own category's total.
 * Categories whose refunds outweigh their purchases are left out, so the total
 * always equals the sum of the categories shown.
 */
export const summarizeSpending = (transactions: Transaction[]): SpendingSummary => {
  // Sum in integer cents: adding floats like 0.1 + 0.2 drifts.
  const centsByCategory = new Map<string, number>();
  for (const t of transactions) {
    if (NON_SPENDING_CATEGORIES.has(t.transaction_type)) continue;
    const cents = Math.round(t.amount * 100);
    centsByCategory.set(t.transaction_type, (centsByCategory.get(t.transaction_type) ?? 0) + cents);
  }

  const categories = Array.from(centsByCategory, ([name, cents]) => ({ name, cents }))
    .filter(c => c.cents > 0)
    .sort((a, b) => b.cents - a.cents);
  const totalCents = categories.reduce((sum, c) => sum + c.cents, 0);

  return {
    total: totalCents / 100,
    categories: categories.map(c => ({ name: c.name, value: c.cents / 100 })),
  };
};

const currencyFormatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

export const formatCurrency = (amount: number): string => currencyFormatter.format(amount);

// For a single transaction, shown the way a bank statement does: money out is negative.
export const formatTransactionAmount = (amount: number): string =>
  amount > 0 ? `-${formatCurrency(amount)}` : `+${formatCurrency(-amount)}`;

// FOOD_AND_DRINK -> Food and drink
export const formatCategory = (category: string): string => {
  const words = category.toLowerCase().split('_');
  return words.join(' ').replace(/^./, c => c.toUpperCase());
};
