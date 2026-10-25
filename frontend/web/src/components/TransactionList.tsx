import { useEffect, useMemo, useState } from 'react';
import { getTransactions, editTransaction, deleteTransaction, Transaction } from '@/services/apiService';
import { formatCategory, formatCurrency, formatTransactionAmount, summarizeSpending } from '@/lib/finance';
import { formatDateTime, getTimeFrameRange, isInTimeFrame, TimeFrame, timeFrameLabels, toDayKey } from '@/lib/dates';
import { transactionsToCsv } from '@/lib/csv';
import { validateTransactionEdit } from '@/lib/transactionEdits';
import {
  Alert,
  List,
  ListItem, 
  ListItemText, 
  Typography, 
  Paper,
  Box,
  CircularProgress,
  Button,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  TextField,
  IconButton,
  Chip,
  Stack,
  Drawer,
  Slider,
  InputAdornment
} from '@mui/material';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import CloseIcon from '@mui/icons-material/Close';
import FilterListIcon from '@mui/icons-material/FilterList';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import DownloadIcon from '@mui/icons-material/Download';


// Plaid personal_finance_category primaries, plus the backend's fallback.
const PLAID_CATEGORIES = [
  'BANK_FEES', 'ENTERTAINMENT', 'FOOD_AND_DRINK', 'GENERAL_MERCHANDISE', 'GENERAL_SERVICES',
  'GOVERNMENT_AND_NON_PROFIT', 'HOME_IMPROVEMENT', 'INCOME', 'LOAN_PAYMENTS', 'MEDICAL',
  'PERSONAL_CARE', 'RENT_AND_UTILITIES', 'TRANSFER_IN', 'TRANSFER_OUT', 'TRANSPORTATION',
  'TRAVEL', 'UNCATEGORIZED',
];

interface TransactionListProps {
  // Changes when a sync finishes; triggers a refetch.
  reloadKey: number;
  isSyncing: boolean;
  onAddAccount: () => void;
}

const COLORS = [
  '#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8', 
  '#82CA9D', '#FFC658', '#FF6B6B', '#4ECDC4', '#45B7D1'
];

interface FilterState {
  category: string;
  minAmount: string;
  maxAmount: string;
}

/**
 * Local state only while the user drags or types; the parent's filters are the
 * source of truth. The parent remounts this (via `key`) when filters or bounds
 * change, which resets the local state to match.
 */
const AmountRangeSlider = ({
  minAmount,
  maxAmount,
  onChange,
  bounds: [lowest, highest]
}: {
  minAmount: string;
  maxAmount: string;
  onChange: (min: string, max: string) => void;
  bounds: [number, number];
}) => {
  const initial = [
    minAmount ? parseFloat(minAmount) : lowest,
    maxAmount ? parseFloat(maxAmount) : highest
  ];
  const [value, setValue] = useState<number[]>(initial);
  const [text, setText] = useState<string[]>(initial.map(String));

  const clamp = (n: number) => Math.min(highest, Math.max(lowest, n));

  const commit = ([a, b]: number[]) => {
    const [low, high] = a <= b ? [a, b] : [b, a];
    setValue([low, high]);
    setText([String(low), String(high)]);
    // A handle at the edge of the range means "no limit", so new data outside it still shows.
    onChange(low <= lowest ? '' : String(low), high >= highest ? '' : String(high));
  };

  // Typed values are applied on blur or Enter, not per keystroke.
  const commitText = () => {
    const [a, b] = text.map(parseFloat);
    commit([Number.isFinite(a) ? clamp(a) : value[0], Number.isFinite(b) ? clamp(b) : value[1]]);
  };

  const textFieldProps = {
    size: 'small' as const,
    onBlur: commitText,
    onKeyDown: (e: React.KeyboardEvent) => { if (e.key === 'Enter') commitText(); },
    inputProps: { inputMode: 'decimal' as const },
    InputProps: { startAdornment: <InputAdornment position="start">$</InputAdornment> },
    sx: { width: '45%' },
  };

  return (
    <Box sx={{ width: '100%', px: 2 }}>
      <Slider
        value={value}
        onChange={(_event, newValue) => {
          if (Array.isArray(newValue)) {
            setValue(newValue);
            setText(newValue.map(String));
          }
        }}
        onChangeCommitted={(_event, newValue) => {
          if (Array.isArray(newValue)) commit(newValue);
        }}
        valueLabelDisplay="auto"
        min={lowest}
        max={highest}
        valueLabelFormat={(v) => formatCurrency(v)}
      />
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
        <TextField {...textFieldProps} label="Min" value={text[0]} onChange={(e) => setText([e.target.value, text[1]])} />
        <TextField {...textFieldProps} label="Max" value={text[1]} onChange={(e) => setText([text[0], e.target.value])} />
      </Box>
    </Box>
  );
};

export default function TransactionList({ reloadKey, isSyncing, onAddAccount }: TransactionListProps) {
  // The only stored copy of the data; every list below is derived from it.
  const [allTransactions, setAllTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [retryCount, setRetryCount] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [timeFrame, setTimeFrame] = useState<TimeFrame>('month');
  const [filters, setFilters] = useState<FilterState>({
    category: '',
    minAmount: '',
    maxAmount: ''
  });
  const [isFilterDrawerOpen, setIsFilterDrawerOpen] = useState(false);
  const [activeTransactionId, setActiveTransactionId] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState<string>('');
  const [editAmount, setEditAmount] = useState('');
  const [editCategory, setEditCategory] = useState('');

  const handleTransactionClick = (transactionId: string) => {
    setActiveTransactionId((prev) => (prev === transactionId ? null : transactionId));
  };

  useEffect(() => {
    // Ignore a response that arrives after a newer fetch started or the component unmounted.
    let cancelled = false;
    const fetchTransactions = async () => {
      try {
        const data = await getTransactions();
        if (cancelled) return;
        // Most recent first
        setAllTransactions([...data].sort((a, b) =>
          new Date(b.datetime).getTime() - new Date(a.datetime).getTime()
        ));
        setLoadError(null);
      } catch (err) {
        if (cancelled) return;
        console.error('Failed to fetch transactions:', err);
        setLoadError('Failed to load transactions.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchTransactions();
    return () => { cancelled = true; };
  }, [reloadKey, retryCount]);

  const transactions = useMemo(() => {
    const range = getTimeFrameRange(timeFrame);
    return allTransactions.filter(transaction => isInTimeFrame(transaction.datetime, range));
  }, [timeFrame, allTransactions]);

  const categories = useMemo(
    () => Array.from(new Set(transactions.map(t => t.transaction_type))).sort(),
    [transactions]
  );

  const filteredTransactions = useMemo(() => {
    let filtered = transactions;

    if (filters.category) {
      filtered = filtered.filter(t => t.transaction_type === filters.category);
    }

    // Empty means unbounded; amounts can be negative (refunds, income).
    const minAmount = filters.minAmount ? parseFloat(filters.minAmount) : -Infinity;
    const maxAmount = filters.maxAmount ? parseFloat(filters.maxAmount) : Infinity;

    if (filters.minAmount || filters.maxAmount) {
      filtered = filtered.filter(t => t.amount >= minAmount && t.amount <= maxAmount);
    }

    return filtered;
  }, [transactions, filters]);

  // Slider range: whole dollars covering every amount in the time frame, always including 0.
  const amountBounds = useMemo((): [number, number] => {
    const amounts = transactions.map(t => t.amount);
    return [Math.floor(Math.min(0, ...amounts)), Math.ceil(Math.max(0, ...amounts))];
  }, [transactions]);

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" p={4}>
        <CircularProgress />
      </Box>
    );
  }

  const summary = summarizeSpending(filteredTransactions);
  const pieData = summary.categories.map(({ name, value }) => ({
    name: formatCategory(name),
    value
  }));

  const handleFilterChange = (field: keyof FilterState, value: string) => {
    setFilters(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const clearFilters = () => {
    setFilters({
      category: '',
      minAmount: '',
      maxAmount: ''
    });
  };

  const hasAmountFilter = Boolean(filters.minAmount || filters.maxAmount);
  // The amount range counts as one filter.
  const activeFiltersCount = (filters.category ? 1 : 0) + (hasAmountFilter ? 1 : 0);

  const handleEditTransaction = async (transactionId: string) => {
    const edit = validateTransactionEdit(editValue, editAmount);
    if (!edit.ok) {
      setActionError(edit.error);
      return;
    }
    try {
      await editTransaction(transactionId, edit.name, String(edit.amount), editCategory);
      setAllTransactions((prev) =>
        prev.map((t) =>
          t.transaction_id === transactionId
            ? { ...t, merchant_name: edit.name, amount: edit.amount, transaction_type: editCategory }
            : t
        )
      );
      setEditingId(null);
      setActionError(null);
    } catch (err) {
      console.error('Failed to edit transaction:', err);
      setActionError(`Failed to save changes: ${err instanceof Error ? err.message : 'unknown error'}`);
    }
  };

  const handleExportCsv = () => {
    const csv = transactionsToCsv(filteredTransactions);
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `transactions-${toDayKey(new Date())}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const handleDeleteTransaction = async (transactionId: string) => {
    if (!window.confirm('Are you sure you want to delete this transaction?')) return;
    try {
      await deleteTransaction(transactionId);
      setAllTransactions((prev) => prev.filter(t => t.transaction_id !== transactionId));
      setActionError(null);
    } catch (err) {
      console.error('Failed to delete transaction:', err);
      setActionError(`Failed to delete transaction: ${err instanceof Error ? err.message : 'unknown error'}`);
    }
  };

  const handleEditClick = (transaction: Transaction) => {
    setEditingId(transaction.transaction_id);
    setEditValue(transaction.merchant_name || transaction.description);
    setEditAmount(transaction.amount.toString());
    setEditCategory(transaction.transaction_type);
  };

  // Plaid's primary categories, plus the transaction's current one in case it's custom.
  const editCategoryOptions = Array.from(new Set([...PLAID_CATEGORIES, editCategory])).filter(Boolean);

  return (
    <Paper elevation={2} sx={{ maxWidth: 800, mx: 'auto', mt: 4, p: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 2, mb: 3, flexWrap: 'wrap' }}>
        <Typography variant="h5">
          Recent Transactions
        </Typography>
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
          <Button
            variant="outlined"
            startIcon={<DownloadIcon />}
            onClick={handleExportCsv}
            disabled={filteredTransactions.length === 0}
            size="small"
          >
            Export CSV
          </Button>
          <FormControl sx={{ minWidth: 150 }}>
            <InputLabel id="time-frame-label">Time Frame</InputLabel>
            <Select
              labelId="time-frame-label"
              value={timeFrame}
              label="Time Frame"
              onChange={(e) => setTimeFrame(e.target.value as TimeFrame)}
              size="small"
            >
              {Object.entries(timeFrameLabels).map(([value, label]) => (
                <MenuItem key={value} value={value}>
                  {label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button
            variant="outlined"
            startIcon={<FilterListIcon />}
            onClick={() => setIsFilterDrawerOpen(true)}
            size="small"
          >
            Filters {activeFiltersCount > 0 && `(${activeFiltersCount})`}
          </Button>
        </Box>
      </Box>

      {loadError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" size="small" onClick={() => setRetryCount(count => count + 1)}>
              Retry
            </Button>
          }
        >
          {loadError}
        </Alert>
      )}
      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      {/* Active Filters */}
      {activeFiltersCount > 0 && (
        <Stack direction="row" spacing={1} sx={{ mb: 3, flexWrap: 'wrap', gap: 1 }}>
          {filters.category && (
            <Chip 
              label={`Category: ${formatCategory(filters.category)}`}
              onDelete={() => handleFilterChange('category', '')}
              size="small"
            />
          )}
          {hasAmountFilter && (
            <Chip
              label={`Amount: ${filters.minAmount ? formatCurrency(parseFloat(filters.minAmount)) : 'Any'} to ${filters.maxAmount ? formatCurrency(parseFloat(filters.maxAmount)) : 'Any'}`}
              onDelete={() => setFilters(prev => ({ ...prev, minAmount: '', maxAmount: '' }))}
              size="small"
            />
          )}
        </Stack>
      )}

      {/* Filter Drawer */}
      <Drawer
        anchor="right"
        open={isFilterDrawerOpen}
        onClose={() => setIsFilterDrawerOpen(false)}
      >
        <Box sx={{ width: 300, p: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
            <Typography variant="h6">Filters</Typography>
            <IconButton onClick={() => setIsFilterDrawerOpen(false)} size="small">
              <CloseIcon />
            </IconButton>
          </Box>

          <Typography variant="subtitle2" sx={{ mb: 1 }}>Category</Typography>
          <FormControl fullWidth size="small" sx={{ mb: 3 }}>
            <Select
              value={filters.category}
              onChange={(e) => handleFilterChange('category', e.target.value)}
              displayEmpty
            >
              <MenuItem value="">All Categories</MenuItem>
              {categories.map(category => (
                <MenuItem key={category} value={category}>
                  {formatCategory(category)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <Typography variant="subtitle2">Amount Range</Typography>
          <Typography variant="caption" color="textSecondary" sx={{ display: 'block', mb: 1 }}>
            Positive = money out; negative = refunds and income
          </Typography>
          <AmountRangeSlider
            // Remount when filters or bounds change elsewhere (Clear All, chip, time frame).
            key={`${filters.minAmount}|${filters.maxAmount}|${amountBounds.join('|')}`}
            minAmount={filters.minAmount}
            maxAmount={filters.maxAmount}
            onChange={(min, max) => setFilters(prev => ({ ...prev, minAmount: min, maxAmount: max }))}
            bounds={amountBounds}
          />

          <Box sx={{ mt: 3, display: 'flex', gap: 2 }}>
            <Button
              fullWidth
              variant="outlined"
              onClick={clearFilters}
              size="small"
            >
              Clear All
            </Button>
            <Button
              fullWidth
              variant="contained"
              onClick={() => setIsFilterDrawerOpen(false)}
              size="small"
            >
              Apply
            </Button>
          </Box>
        </Box>
      </Drawer>

      {/* Transaction Summary */}
      <Box 
        sx={{ 
          display: 'flex', 
          justifyContent: 'center',
          mb: 3,
          p: 2,
          bgcolor: 'background.default',
          borderRadius: 1
        }}
      >
        <Box>
          <Typography variant="subtitle2" color="textSecondary">
            Net Spending {activeFiltersCount > 0 && '(Filtered)'}
          </Typography>
          <Typography variant="h6" color="error.main">
            {formatCurrency(summary.total)}
          </Typography>
          <Typography variant="caption" color="textSecondary">
            Refunds included; transfers, loan payments and income excluded
          </Typography>
        </Box>
      </Box>

      {/* Spending Categories Pie Chart */}
      {pieData.length > 0 && (
        <Box sx={{ height: 300, mb: 3 }}>
          <Typography variant="h6" gutterBottom align="center">
            Spending by Category
          </Typography>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={pieData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={40}
                outerRadius={100}
                label={false}
              >
                {pieData.map((entry, index) => (
                  <Cell 
                    key={`cell-${index}`} 
                    fill={COLORS[index % COLORS.length]}
                  />
                ))}
              </Pie>
              <Tooltip 
                formatter={(value: number, name: string) => {
                  const total = pieData.reduce((sum, item) => sum + item.value, 0);
                  const percentage = ((value / total) * 100).toFixed(1);
                  return [`${formatCurrency(value)} (${percentage}%)`, name];
                }}
              />
              <Legend 
                layout="vertical" 
                align="right"
                verticalAlign="middle"
                iconSize={8}
                wrapperStyle={{
                  fontSize: '12px',
                  paddingLeft: '20px'
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </Box>
      )}

      {filteredTransactions.length === 0 ? (
        <Typography align="center" color="textSecondary" sx={{ my: 4 }}>
          {isSyncing && allTransactions.length === 0
            ? 'Your transactions are syncing. They will appear here when the sync finishes.'
            : 'No transactions found'}
        </Typography>
      ) : (
        <List>
          {filteredTransactions.map((transaction) => {
            const { date, time } = formatDateTime(transaction.datetime);
            return (
              <ListItem
                key={transaction.transaction_id}
                divider
                sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', py: 2 }}
              >
                {editingId === transaction.transaction_id ? (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flex: 1, flexWrap: 'wrap' }}>
                    <TextField
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      size="small"
                      fullWidth
                      label="Name"
                    />
                    <TextField
                      value={editAmount}
                      onChange={(e) => setEditAmount(e.target.value)}
                      size="small"
                      label="Amount"
                      helperText="Positive = money out"
                      inputProps={{ inputMode: 'decimal' }}
                      sx={{ width: 120 }}
                    />
                    <TextField
                      select
                      value={editCategory}
                      onChange={(e) => setEditCategory(e.target.value)}
                      size="small"
                      label="Category"
                      sx={{ minWidth: 180 }}
                    >
                      {editCategoryOptions.map(category => (
                        <MenuItem key={category} value={category}>
                          {formatCategory(category)}
                        </MenuItem>
                      ))}
                    </TextField>
                    <Button variant="contained" size="small" onClick={() => handleEditTransaction(transaction.transaction_id)}>
                      Save
                    </Button>
                    <Button size="small" onClick={() => setEditingId(null)}>
                      Cancel
                    </Button>
                  </Box>
                ) : (
                  <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto 112px', alignItems: 'center', gap: 1, width: '100%' }}>
                    <Box sx={{ minWidth: 0 }}>
                      <ListItemText
                        primary={transaction.merchant_name || transaction.description}
                        secondary={
                          <Box component="span" sx={{ display: 'block' }}>
                            <Typography variant="body2" component="span" color="textSecondary">
                              {date}
                            </Typography>
                            {time && (
                              <Typography 
                                variant="body2" 
                                component="span" 
                                color="textSecondary" 
                                sx={{ ml: 1 }}
                              >
                                {time}
                              </Typography>
                            )}
                            <Typography
                              variant="body2"
                              component="span"
                              color="textSecondary"
                              sx={{ mt: 0.5, display: 'block' }}
                            >
                              {transaction.account.institution !== 'Unknown' ? `${transaction.account.institution} • ` : ''}{transaction.account.name} • {formatCategory(transaction.transaction_type)}
                            </Typography>
                          </Box>
                        }
                      />
                    </Box>
                    <Typography
                      variant="body1"
                      style={{ color: transaction.amount > 0 ? '#d32f2f' : '#2e7d32' }}
                      sx={{ fontWeight: 'medium', whiteSpace: 'nowrap', textAlign: 'right' }}
                    >
                      {formatTransactionAmount(transaction.amount)}
                    </Typography>
                    <Box sx={{ width: 112, display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 0.5 }}>
                      <IconButton
                        onClick={() => handleTransactionClick(transaction.transaction_id)}
                        size="small"
                        aria-label={`Transaction actions for ${transaction.merchant_name || transaction.description}`}
                        aria-expanded={activeTransactionId === transaction.transaction_id}
                      >
                        {activeTransactionId === transaction.transaction_id ? <CloseIcon /> : <MoreVertIcon />}
                      </IconButton>
                      {activeTransactionId === transaction.transaction_id && (
                        <>
                        <IconButton onClick={() => handleEditClick(transaction)} size="small" aria-label="Edit transaction">
                          <EditIcon />
                        </IconButton>
                        <IconButton onClick={() => handleDeleteTransaction(transaction.transaction_id)} size="small" aria-label="Delete transaction">
                          <DeleteIcon />
                        </IconButton>
                        </>
                      )}
                    </Box>
                  </Box>
                )}
              </ListItem>
            );
          })}
        </List>
      )}
      <Box sx={{ mt: 3, textAlign: 'center' }}>
        <Button
          variant="outlined"
          color="primary"
          onClick={onAddAccount}
          sx={{ minWidth: 200 }}
        >
          Add Another Account
        </Button>
      </Box>
    </Paper>
  );
} 