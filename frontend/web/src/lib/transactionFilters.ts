import type { Transaction } from '@/services/apiService';

export interface TransactionFilters {
  search: string;
  category: string;
  minAmount: string;
  maxAmount: string;
}

export const filterTransactions = (
  transactions: Transaction[],
  filters: TransactionFilters,
): Transaction[] => {
  const query = filters.search.trim().toLocaleLowerCase();
  const minAmount = filters.minAmount ? Number(filters.minAmount) : -Infinity;
  const maxAmount = filters.maxAmount ? Number(filters.maxAmount) : Infinity;

  return transactions.filter(transaction => {
    if (filters.category && transaction.transaction_type !== filters.category) {
      return false;
    }

    if ((filters.minAmount || filters.maxAmount) &&
      (transaction.amount < minAmount || transaction.amount > maxAmount)) {
      return false;
    }

    if (!query) {
      return true;
    }

    return [
      transaction.merchant_name,
      transaction.description,
      transaction.transaction_type,
      transaction.account.name,
      transaction.account.institution,
    ]
      .some(value => value?.toLocaleLowerCase().includes(query));
  });
};
