import { describe, expect, it } from 'vitest';
import type { Transaction } from '@/services/apiService';
import { filterTransactions } from './transactionFilters';

const transactions: Transaction[] = [
  {
    transaction_id: 'coffee',
    amount: 8.5,
    description: 'Card purchase',
    merchant_name: 'Blue Bottle Coffee',
    datetime: '2024-03-10T12:00:00Z',
    transaction_type: 'FOOD_AND_DRINK',
    payment_channel: 'in store',
    account: { name: 'Checking', account_type: 'depository', institution: 'First Bank' },
  },
  {
    transaction_id: 'refund',
    amount: -8.5,
    description: 'Coffee refund',
    merchant_name: 'Blue Bottle Coffee',
    datetime: '2024-03-11T12:00:00Z',
    transaction_type: 'FOOD_AND_DRINK',
    payment_channel: 'in store',
    account: { name: 'Credit Card', account_type: 'credit', institution: 'Second Bank' },
  },
  {
    transaction_id: 'rent',
    amount: 1200,
    description: 'Monthly rent',
    merchant_name: null,
    datetime: '2024-03-01T12:00:00Z',
    transaction_type: 'RENT_AND_UTILITIES',
    payment_channel: 'online',
    account: { name: 'Checking', account_type: 'depository', institution: 'First Bank' },
  },
];

const emptyFilters = { search: '', category: '', minAmount: '', maxAmount: '' };

describe('filterTransactions', () => {
  it('searches case-insensitively across merchant, description, category, and account names', () => {
    expect(filterTransactions(transactions, { ...emptyFilters, search: '  BLUE BOTTLE ' }))
      .toEqual(transactions.slice(0, 2));
    expect(filterTransactions(transactions, { ...emptyFilters, search: 'monthly rent' }))
      .toEqual([transactions[2]]);
    expect(filterTransactions(transactions, { ...emptyFilters, search: 'second bank' }))
      .toEqual([transactions[1]]);
  });

  it('applies search, category, and signed amount range together', () => {
    expect(filterTransactions(transactions, {
      search: 'coffee',
      category: 'FOOD_AND_DRINK',
      minAmount: '-10',
      maxAmount: '-1',
    })).toEqual([transactions[1]]);
  });

  it('treats blank amount bounds as unbounded and blank search as no search', () => {
    expect(filterTransactions(transactions, {
      ...emptyFilters,
      search: '  ',
      minAmount: '8',
    })).toEqual([transactions[0], transactions[2]]);
  });
});
