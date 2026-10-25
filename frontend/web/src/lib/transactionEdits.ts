export type TransactionEditValidation =
  | { ok: true; name: string; amount: number }
  | { ok: false; error: 'Name cannot be blank.' | 'Amount must be a number.' };

export const validateTransactionEdit = (nameInput: string, amountInput: string): TransactionEditValidation => {
  const name = nameInput.trim();
  if (!name) {
    return { ok: false, error: 'Name cannot be blank.' };
  }

  if (!amountInput.trim()) {
    return { ok: false, error: 'Amount must be a number.' };
  }
  const amount = Number(amountInput);
  if (!Number.isFinite(amount)) {
    return { ok: false, error: 'Amount must be a number.' };
  }

  return { ok: true, name, amount };
};
