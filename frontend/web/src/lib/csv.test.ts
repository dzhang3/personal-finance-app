import { describe, expect, it } from 'vitest';
import type { Transaction } from '@/services/apiService';
import { transactionsToCsv } from './csv';

const transaction: Transaction = {
  transaction_id: 'transaction-1',
  amount: -12.5,
  description: 'Refund, "store"',
  merchant_name: '=HYPERLINK("https://example.test")',
  datetime: '2024-03-10T12:00:00Z',
  transaction_type: 'FOOD_AND_DRINK',
  payment_channel: null,
  account: { name: 'Checking', account_type: 'depository', institution: 'Test Bank' },
};

describe('transactionsToCsv', () => {
  it('exports signed amounts and quotes commas, quotes, and empty values', () => {
    expect(transactionsToCsv([transaction])).toBe([
      '"Date","Merchant","Description","Amount","Category","Account","Account Type","Institution","Payment Channel"',
      '"2024-03-10T12:00:00Z","\'=HYPERLINK(""https://example.test"")","Refund, ""store""","-12.5","Food and drink","Checking","depository","Test Bank",""',
    ].join('\r\n'));
  });

  it('returns just the headers when there are no matching transactions', () => {
    expect(transactionsToCsv([])).toBe(
      '"Date","Merchant","Description","Amount","Category","Account","Account Type","Institution","Payment Channel"',
    );
  });
});
