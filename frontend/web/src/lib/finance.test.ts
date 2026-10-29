import { describe, expect, it } from 'vitest';
import type { Transaction } from '@/services/apiService';
import { formatTransactionAmount, summarizeSpending } from './finance';

const transaction = (amount: number, transaction_type: string): Transaction => ({
  transaction_id: `${transaction_type}-${amount}`,
  amount,
  description: 'Test transaction',
  merchant_name: null,
  datetime: '2024-03-10T12:00:00Z',
  transaction_type,
  payment_channel: 'online',
  account: { name: 'Checking', account_type: 'depository', institution: 'Test Bank' },
});

describe('transaction amount formatting', () => {
  it('shows spending as negative and refunds as positive on a bank statement', () => {
    expect(formatTransactionAmount(12.34)).toBe('-$12.34');
    expect(formatTransactionAmount(-5.25)).toBe('+$5.25');
    expect(formatTransactionAmount(0)).toBe('$0.00');
  });
});

describe('summarizeSpending', () => {
  it('nets refunds against spending and excludes transfers, loan payments, and income', () => {
    const summary = summarizeSpending([
      transaction(20.1, 'FOOD_AND_DRINK'),
      transaction(-5.1, 'FOOD_AND_DRINK'),
      transaction(80, 'TRANSFER_OUT'),
      transaction(40, 'TRANSFER_IN'),
      transaction(30, 'LOAN_PAYMENTS'),
      transaction(-200, 'INCOME'),
      transaction(8, 'TRANSPORTATION'),
    ]);

    expect(summary).toEqual({
      total: 23,
      categories: [
        { name: 'FOOD_AND_DRINK', value: 15 },
        { name: 'TRANSPORTATION', value: 8 },
      ],
    });
  });

  it('does not show categories with a non-positive net total', () => {
    expect(summarizeSpending([
      transaction(10, 'FOOD_AND_DRINK'),
      transaction(-12, 'FOOD_AND_DRINK'),
    ])).toEqual({ total: 0, categories: [] });
  });
});
