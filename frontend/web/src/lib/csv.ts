import type { Transaction } from '@/services/apiService';
import { formatCategory } from './finance';

const escapeTextCell = (value: string | null): string => {
  const text = value ?? '';
  const safeText = /^[\u0000-\u0020]*[=+\-@]/.test(text) ? `'${text}` : text;
  return `"${safeText.replaceAll('"', '""')}"`;
};

const escapeCell = (value: string | number | null): string =>
  typeof value === 'string' || value === null
    ? escapeTextCell(value)
    : `"${String(value)}"`;

const HEADERS = [
  'Date',
  'Merchant',
  'Description',
  'Amount',
  'Category',
  'Account',
  'Account Type',
  'Institution',
  'Payment Channel',
];

export const transactionsToCsv = (transactions: Transaction[]): string => {
  const rows = transactions.map(transaction => [
    transaction.datetime,
    transaction.merchant_name || transaction.description,
    transaction.description,
    transaction.amount,
    formatCategory(transaction.transaction_type),
    transaction.account.name,
    transaction.account.account_type,
    transaction.account.institution,
    transaction.payment_channel,
  ]);

  return [HEADERS, ...rows]
    .map(row => row.map(escapeCell).join(','))
    .join('\r\n');
};
