import { useEffect, useState } from 'react';
import { getTransactions } from '@services';
import { 
  List, 
  ListItem, 
  ListItemText, 
  Typography, 
  Paper,
  Box,
  CircularProgress,
  Button,
  useTheme,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  TextField,
  IconButton,
  Chip,
  Stack,
  Drawer,
  Divider,
  Slider,
  InputAdornment
} from '@mui/material';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import CloseIcon from '@mui/icons-material/Close';
import FilterListIcon from '@mui/icons-material/FilterList';

interface Transaction {
  transaction_id: string;
  amount: number;
  description: string;
  merchant_name: string | null;
  datetime: string;
  transaction_type: string;
  account: {
    name: string;
    account_type: string;
    institution: string;
  };
}

interface TransactionSummary {
  expenses: number;
  categories: Record<string, number>;
}

interface TransactionListProps {
  onAddAccount: () => void;
}

type TimeFrame = 'all' | 'week' | 'month' | 'prevMonth' | 'ytd' | 'year';

const getTimeFrameStart = (timeFrame: TimeFrame): Date => {
  const now = new Date();
  switch (timeFrame) {
    case 'week':
      const weekStart = new Date(now);
      weekStart.setDate(now.getDate() - now.getDay()); // Start of current week (Sunday)
      return weekStart;
    case 'month':
      return new Date(now.getFullYear(), now.getMonth(), 1); // Start of current month
    case 'prevMonth':
      return new Date(now.getFullYear(), now.getMonth() - 1, 1); // Start of previous month
    case 'ytd':
      return new Date(now.getFullYear(), 0, 1); // Start of current year
    case 'year':
      const yearStart = new Date(now.getFullYear(), 0, 1); // Start of current year
      yearStart.setFullYear(yearStart.getFullYear() - 1); // Go back one year
      return yearStart;
    default:
      return new Date(0); // Beginning of time for 'all'
  }
};

const getTimeFrameEnd = (timeFrame: TimeFrame): Date => {
  const now = new Date();
  if (timeFrame === 'prevMonth') {
    return new Date(now.getFullYear(), now.getMonth(), 0); // End of previous month
  }
  return now;
};

const timeFrameLabels: Record<TimeFrame, string> = {
  all: 'All Time',
  week: 'This Week',
  month: 'This Month',
  prevMonth: 'Previous Month',
  ytd: 'Year to Date',
  year: 'Last 12 Months'
};

const formatDateTime = (isoString: string) => {
  const date = new Date(isoString);
  
  // Format date
  const dateOptions: Intl.DateTimeFormatOptions = {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  };
  
  // Check if the time is midnight (00:00:00) which likely means it's a date-only value
  const isDateOnly = date.getUTCHours() === 0 && 
                    date.getUTCMinutes() === 0 && 
                    date.getUTCSeconds() === 0;
  
  // Only format time if it's not midnight
  const time = !isDateOnly ? date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  }) : null;
  
  return {
    date: date.toLocaleDateString('en-US', dateOptions),
    time,
  };
};

const calculateTransactionSummary = (transactions: Transaction[]): TransactionSummary => {
  return transactions.reduce((summary, transaction) => {
    // All transactions from backend are now expenses (positive amounts)
    summary.expenses += transaction.amount;
    // Add to category total
    const categories: Record<string, number> = summary.categories;
    categories[transaction.transaction_type] = (categories[transaction.transaction_type] || 0) + transaction.amount;
    return summary;
  }, { expenses: 0, categories: {} as Record<string, number> });
};

const formatCurrency = (amount: number): string => {
  return `$${amount.toFixed(2)}`;
};

const COLORS = [
  '#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8', 
  '#82CA9D', '#FFC658', '#FF6B6B', '#4ECDC4', '#45B7D1'
];

interface FilterState {
  category: string;
  minAmount: string;
  maxAmount: string;
}

// Add this new component for the amount slider
const AmountRangeSlider = ({ 
  minAmount, 
  maxAmount, 
  onChange,
  maxPossibleAmount
}: { 
  minAmount: string; 
  maxAmount: string; 
  onChange: (min: string, max: string) => void;
  maxPossibleAmount: number;
}) => {
  const [value, setValue] = useState<number[]>([
    minAmount ? parseFloat(minAmount) : 0,
    maxAmount ? parseFloat(maxAmount) : maxPossibleAmount
  ]);

  const handleChange = (_event: Event, newValue: number | number[]) => {
    if (Array.isArray(newValue)) {
      setValue(newValue);
    }
  };

  const handleChangeCommitted = (_event: React.SyntheticEvent | Event, newValue: number | number[]) => {
    if (Array.isArray(newValue)) {
      onChange(newValue[0].toString(), newValue[1].toString());
    }
  };

  return (
    <Box sx={{ width: '100%', px: 2 }}>
      <Slider
        value={value}
        onChange={handleChange}
        onChangeCommitted={handleChangeCommitted}
        valueLabelDisplay="auto"
        min={0}
        max={maxPossibleAmount}
        valueLabelFormat={(value) => `$${value}`}
      />
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
        <TextField
          size="small"
          value={value[0]}
          onChange={(e) => {
            const newValue = e.target.value;
            setValue([parseFloat(newValue) || 0, value[1]]);
            onChange(newValue, value[1].toString());
          }}
          InputProps={{
            startAdornment: <InputAdornment position="start">$</InputAdornment>,
          }}
          sx={{ width: '45%' }}
        />
        <TextField
          size="small"
          value={value[1]}
          onChange={(e) => {
            const newValue = e.target.value;
            setValue([value[0], parseFloat(newValue) || maxPossibleAmount]);
            onChange(value[0].toString(), newValue);
          }}
          InputProps={{
            startAdornment: <InputAdornment position="start">$</InputAdornment>,
          }}
          sx={{ width: '45%' }}
        />
      </Box>
    </Box>
  );
};

export default function TransactionList({ onAddAccount }: TransactionListProps) {
  const theme = useTheme();
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [filteredTransactions, setFilteredTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [isSyncing, setIsSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeFrame, setTimeFrame] = useState<TimeFrame>('all');
  const [allTransactions, setAllTransactions] = useState<Transaction[]>([]);
  const [filters, setFilters] = useState<FilterState>({
    category: '',
    minAmount: '',
    maxAmount: ''
  });
  const [categories, setCategories] = useState<string[]>([]);
  const [isFilterDrawerOpen, setIsFilterDrawerOpen] = useState(false);
  const maxAmount = Math.max(...transactions.map(t => t.amount));

  const handleForceSync = async () => {
    try {
      setIsSyncing(true);
      setError(null);
      
      const response = await fetch('http://localhost:8000/api/force_transaction_sync/', {
        method: 'GET',
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to sync transactions');
      }

      // Refetch transactions after sync
      const data = await getTransactions();
      const sortedTransactions = data.sort((a: Transaction, b: Transaction) => 
        new Date(b.datetime).getTime() - new Date(a.datetime).getTime()
      );
      setAllTransactions(sortedTransactions);
    } catch (err) {
      console.error('Failed to sync transactions:', err);
      setError('Failed to sync transactions');
    } finally {
      setIsSyncing(false);
    }
  };

  useEffect(() => {
    const fetchTransactions = async () => {
      try {
        console.log('fetching transactions')
        const data = await getTransactions();
        // Sort transactions by date in descending order (most recent first)
        const sortedTransactions = data.sort((a: Transaction, b: Transaction) => 
          new Date(b.datetime).getTime() - new Date(a.datetime).getTime()
        );
        setAllTransactions(sortedTransactions);
        setLoading(false);
      } catch (err) {
        setError('Failed to fetch transactions');
        setLoading(false);
      }
    };

    fetchTransactions();
  }, []);

  useEffect(() => {
    const startDate = getTimeFrameStart(timeFrame);
    const endDate = getTimeFrameEnd(timeFrame);
    
    const filteredTransactions = allTransactions.filter(transaction => {
      const transactionDate = new Date(transaction.datetime);
      return transactionDate >= startDate && transactionDate <= endDate;
    });
    
    setTransactions(filteredTransactions);
  }, [timeFrame, allTransactions]);

  useEffect(() => {
    // Extract unique categories from transactions
    const uniqueCategories = Array.from(new Set(
      transactions.map(t => t.transaction_type)
    )).sort();
    setCategories(uniqueCategories);
  }, [transactions]);

  useEffect(() => {
    let filtered = [...transactions];

    // Apply category filter
    if (filters.category) {
      filtered = filtered.filter(t => t.transaction_type === filters.category);
    }

    // Apply amount filters
    const minAmount = filters.minAmount ? parseFloat(filters.minAmount) : 0;
    const maxAmount = filters.maxAmount ? parseFloat(filters.maxAmount) : Infinity;

    if (filters.minAmount || filters.maxAmount) {
      filtered = filtered.filter(t => t.amount >= minAmount && t.amount <= maxAmount);
    }

    setFilteredTransactions(filtered);
  }, [transactions, filters]);

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" p={4}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Typography color="error" align="center">
        {error}
      </Typography>
    );
  }

  const summary = calculateTransactionSummary(filteredTransactions);
  const pieData = Object.entries(summary.categories).map(([name, value]) => ({
    name,
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

  const activeFiltersCount = Object.values(filters).filter(Boolean).length;

  return (
    <Paper elevation={2} sx={{ maxWidth: 800, mx: 'auto', mt: 4, p: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h5">
          Recent Transactions
        </Typography>
        <Box sx={{ display: 'flex', gap: 2 }}>
          <Button
            variant="outlined"
            onClick={handleForceSync}
            disabled={isSyncing}
            startIcon={isSyncing ? <CircularProgress size={20} /> : null}
            size="small"
          >
            {isSyncing ? 'Syncing...' : 'Refresh Transactions'}
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

      {/* Active Filters */}
      {activeFiltersCount > 0 && (
        <Stack direction="row" spacing={1} sx={{ mb: 3, flexWrap: 'wrap', gap: 1 }}>
          {filters.category && (
            <Chip 
              label={`Category: ${filters.category}`}
              onDelete={() => handleFilterChange('category', '')}
              size="small"
            />
          )}
          {(filters.minAmount || filters.maxAmount) && (
            <Chip 
              label={`Amount: ${filters.minAmount ? `$${filters.minAmount}` : '$0'} - ${filters.maxAmount ? `$${filters.maxAmount}` : 'Any'}`}
              onDelete={() => {
                handleFilterChange('minAmount', '');
                handleFilterChange('maxAmount', '');
              }}
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
                  {category}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <Typography variant="subtitle2" sx={{ mb: 1 }}>Price Range</Typography>
          <AmountRangeSlider
            minAmount={filters.minAmount}
            maxAmount={filters.maxAmount}
            onChange={(min, max) => {
              handleFilterChange('minAmount', min);
              handleFilterChange('maxAmount', max);
            }}
            maxPossibleAmount={maxAmount}
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
            Total Expenses {activeFiltersCount > 0 && '(Filtered)'}
          </Typography>
          <Typography variant="h6" color="error.main">
            {formatCurrency(summary.expenses)}
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
                formatter={(value: number, name: string, props: any) => {
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
          No transactions found
        </Typography>
      ) : (
        <List>
          {filteredTransactions.map((transaction) => {
            const { date, time } = formatDateTime(transaction.datetime);
            return (
              <ListItem
                key={transaction.transaction_id}
                divider
                sx={{ 
                  display: 'flex', 
                  justifyContent: 'space-between',
                  py: 2
                }}
              >
                <Box sx={{ flex: 1 }}>
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
                          component="div" 
                          color="textSecondary"
                          sx={{ mt: 0.5 }}
                        >
                          {transaction.account.institution !== 'Unknown' ? `${transaction.account.institution} • ` : ''}{transaction.account.name} • {transaction.transaction_type}
                        </Typography>
                      </Box>
                    }
                  />
                </Box>
                <Typography
                  variant="body1"
                  color={transaction.amount > 0 ? 'error.main' : 'success.main'}
                  sx={{ fontWeight: 'medium', ml: 2 }}
                >
                  ${Math.abs(transaction.amount).toFixed(2)}
                </Typography>
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