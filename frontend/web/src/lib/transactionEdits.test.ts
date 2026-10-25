import { describe, expect, it } from 'vitest';
import { validateTransactionEdit } from './transactionEdits';

describe('validateTransactionEdit', () => {
  it('trims names and accepts negative refund amounts', () => {
    expect(validateTransactionEdit('  Refund  ', '-12.50')).toEqual({
      ok: true,
      name: 'Refund',
      amount: -12.5,
    });
  });

  it('rejects blank names', () => {
    expect(validateTransactionEdit('   ', '10')).toEqual({
      ok: false,
      error: 'Name cannot be blank.',
    });
  });

  it.each(['', 'not a number', 'Infinity'])('rejects invalid amount %j', amount => {
    expect(validateTransactionEdit('Purchase', amount)).toEqual({
      ok: false,
      error: 'Amount must be a number.',
    });
  });
});
