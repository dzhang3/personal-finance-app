'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControl,
  IconButton,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import {
  BudgetTarget,
  deleteBudgetTarget,
  getBudgetTargets,
  saveBudgetTarget,
  Transaction,
} from '@/services/apiService';
import { NON_SPENDING_CATEGORIES, formatCategory, formatCurrency, summarizeSpending } from '@/lib/finance';
import { getTimeFrameRange, isInTimeFrame } from '@/lib/dates';

interface BudgetPanelProps {
  transactions: Transaction[];
}

const progressPercent = (spent: number, limit: number) => Math.min((spent / limit) * 100, 100);

export default function BudgetPanel({ transactions }: BudgetPanelProps) {
  const [targets, setTargets] = useState<BudgetTarget[]>([]);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [newCategory, setNewCategory] = useState('');
  const [newAmount, setNewAmount] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [savingCategory, setSavingCategory] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const nextTargets = await getBudgetTargets();
        if (cancelled) return;
        setTargets(nextTargets);
        setAmounts(Object.fromEntries(nextTargets.map(target => [target.category, target.monthly_limit])));
        setLoadFailed(false);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to load budget targets:', err);
          setLoadFailed(true);
          setError('Could not load budget targets.');
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [loadAttempt]);

  const monthTransactions = useMemo(() => {
    const month = getTimeFrameRange('month');
    return transactions.filter(transaction => isInTimeFrame(transaction.datetime, month));
  }, [transactions]);
  const spending = useMemo(() => summarizeSpending(monthTransactions), [monthTransactions]);
  const spendingByCategory = useMemo(
    () => new Map(spending.categories.map(category => [category.name, category.value])),
    [spending.categories],
  );
  const categories = useMemo(() => Array.from(new Set([
    ...transactions.map(transaction => transaction.transaction_type),
    ...targets.map(target => target.category),
  ]))
    .filter(category => category && !NON_SPENDING_CATEGORIES.has(category))
    .sort(), [transactions, targets]);
  const overallTarget = targets.find(target => target.category === '');
  const categoryTargets = targets.filter(target => target.category !== '');

  const saveTarget = async (category: string, amount: string) => {
    if (!amount.trim()) {
      setError('Enter a positive monthly target.');
      return;
    }
    const numericAmount = Number(amount);
    if (!Number.isFinite(numericAmount) || numericAmount <= 0) {
      setError('Enter a positive monthly target.');
      return;
    }

    setSavingCategory(category);
    setError(null);
    try {
      const saved = await saveBudgetTarget(category, numericAmount.toFixed(2));
      setTargets(previous => [
        ...previous.filter(target => target.category !== category),
        saved,
      ].sort((a, b) => a.category.localeCompare(b.category)));
      setAmounts(previous => ({ ...previous, [category]: saved.monthly_limit }));
      if (category !== '') {
        setNewCategory('');
        setNewAmount('');
      }
    } catch (err) {
      console.error('Failed to save budget target:', err);
      setError('Could not save this monthly target. Please try again.');
    } finally {
      setSavingCategory(null);
    }
  };

  const removeTarget = async (category: string) => {
    setSavingCategory(category);
    setError(null);
    try {
      await deleteBudgetTarget(category);
      setTargets(previous => previous.filter(target => target.category !== category));
      setAmounts(previous => {
        const next = { ...previous };
        delete next[category];
        return next;
      });
    } catch (err) {
      console.error('Failed to delete budget target:', err);
      setError('Could not remove this monthly target. Please try again.');
    } finally {
      setSavingCategory(null);
    }
  };

  const renderProgress = (label: string, spent: number, limit: number) => {
    const overBudget = spent > limit;
    return (
      <Box sx={{ minWidth: 160, flex: 1 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
          <Typography variant="body2">{label}</Typography>
          <Typography variant="body2" color={overBudget ? 'error.main' : 'text.secondary'}>
            {formatCurrency(spent)} / {formatCurrency(limit)}
          </Typography>
        </Box>
        <LinearProgress
          variant="determinate"
          value={progressPercent(spent, limit)}
          color={overBudget ? 'error' : 'primary'}
          sx={{ mt: 0.75, height: 8, borderRadius: 4 }}
          aria-label={`${label} budget progress`}
        />
        {overBudget && (
          <Typography variant="caption" color="error.main">
            Over by {formatCurrency(spent - limit)}
          </Typography>
        )}
      </Box>
    );
  };

  return (
    <Paper elevation={2} sx={{ maxWidth: 800, mx: 'auto', mt: 3, p: 2 }}>
      <Typography variant="h6" component="h2" gutterBottom>
        Monthly spending targets
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Targets reset each month. Progress uses net spending; transfers, loan payments, and income are excluded.
      </Typography>

      {error && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={loadFailed ? (
            <Button color="inherit" size="small" onClick={() => {
              setIsLoading(true);
              setLoadAttempt(attempt => attempt + 1);
            }}>
              Retry
            </Button>
          ) : undefined}
        >
          {error}
        </Alert>
      )}
      {isLoading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
          <CircularProgress size={24} />
        </Box>
      ) : loadFailed ? null : (
        <Stack spacing={2}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
            <TextField
              label="Overall monthly target (optional)"
              type="number"
              size="small"
              value={amounts[''] ?? ''}
              onChange={event => setAmounts(previous => ({ ...previous, '': event.target.value }))}
              inputProps={{ min: 0.01, step: 0.01, inputMode: 'decimal' }}
              sx={{ width: { xs: '100%', sm: 240 } }}
            />
            <Button
              variant="contained"
              onClick={() => void saveTarget('', amounts[''] ?? '')}
              disabled={savingCategory !== null}
            >
              Save overall target
            </Button>
            {overallTarget && (
              <Button
                color="inherit"
                onClick={() => void removeTarget('')}
                disabled={savingCategory !== null}
              >
                Remove
              </Button>
            )}
            {overallTarget && renderProgress('Overall', spending.total, Number(overallTarget.monthly_limit))}
          </Box>

          {categoryTargets.map(target => {
            const spent = spendingByCategory.get(target.category) ?? 0;
            return (
              <Box key={target.category} sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
                {renderProgress(formatCategory(target.category), spent, Number(target.monthly_limit))}
                <TextField
                  label="Monthly target"
                  type="number"
                  size="small"
                  value={amounts[target.category] ?? target.monthly_limit}
                  onChange={event => setAmounts(previous => ({ ...previous, [target.category]: event.target.value }))}
                  inputProps={{ min: 0.01, step: 0.01, inputMode: 'decimal' }}
                  sx={{ width: 150 }}
                />
                <Button
                  size="small"
                  onClick={() => void saveTarget(target.category, amounts[target.category] ?? target.monthly_limit)}
                  disabled={savingCategory !== null}
                >
                  Save
                </Button>
                <IconButton
                  aria-label={`Remove ${formatCategory(target.category)} target`}
                  onClick={() => void removeTarget(target.category)}
                  disabled={savingCategory !== null}
                  size="small"
                >
                  <DeleteIcon />
                </IconButton>
              </Box>
            );
          })}

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap', pt: 1, borderTop: 1, borderColor: 'divider' }}>
            <FormControl size="small" sx={{ minWidth: 220 }}>
              <InputLabel id="budget-category-label">Category target</InputLabel>
              <Select
                labelId="budget-category-label"
                label="Category target"
                value={newCategory}
                onChange={event => setNewCategory(event.target.value)}
              >
                {categories.filter(category => !categoryTargets.some(target => target.category === category))
                  .map(category => (
                    <MenuItem key={category} value={category}>{formatCategory(category)}</MenuItem>
                  ))}
              </Select>
            </FormControl>
            <TextField
              label="Monthly target"
              type="number"
              size="small"
              value={newAmount}
              onChange={event => setNewAmount(event.target.value)}
              inputProps={{ min: 0.01, step: 0.01, inputMode: 'decimal' }}
              sx={{ width: 150 }}
            />
            <Button
              variant="outlined"
              onClick={() => void saveTarget(newCategory, newAmount)}
              disabled={!newCategory || !newAmount || savingCategory !== null}
            >
              Add category target
            </Button>
          </Box>
          {categories.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              Category targets are available after transactions have synced.
            </Typography>
          )}
        </Stack>
      )}
    </Paper>
  );
}
