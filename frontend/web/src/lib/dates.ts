// Must match Django's TIME_ZONE: date-only transactions are stored as midnight there.
export const APP_TIME_ZONE = 'America/New_York';

export type TimeFrame = 'all' | 'week' | 'month' | 'prevMonth' | 'ytd' | 'year';

export const timeFrameLabels: Record<TimeFrame, string> = {
  all: 'All Time',
  week: 'This Week',
  month: 'This Month',
  prevMonth: 'Previous Month',
  ytd: 'Year to Date',
  year: 'Last 12 Months'
};

const partsFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: APP_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

const zonedParts = (date: Date) => {
  const parts: Record<string, string> = {};
  for (const { type, value } of partsFormatter.formatToParts(date)) {
    parts[type] = value;
  }
  return parts;
};

// The calendar day in APP_TIME_ZONE as 'YYYY-MM-DD'. These compare correctly as strings.
export const toDayKey = (date: Date): string => {
  const { year, month, day } = zonedParts(date);
  return `${year}-${month}-${day}`;
};

// Calendar arithmetic on day keys. UTC here is just a time-zone-free calendar, so no DST surprises.
const shiftDays = (dayKey: string, days: number): string => {
  const d = new Date(`${dayKey}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

/** Inclusive [start, end] day keys for a time frame; null means unbounded. */
export const getTimeFrameRange = (timeFrame: TimeFrame, now = new Date()): { start: string | null; end: string | null } => {
  const today = toDayKey(now);
  const [year, month, day] = today.split('-').map(Number);
  const pad = (n: number) => String(n).padStart(2, '0');

  switch (timeFrame) {
    case 'week': {
      const weekday = new Date(`${today}T00:00:00Z`).getUTCDay(); // 0 = Sunday
      return { start: shiftDays(today, -weekday), end: null };
    }
    case 'month':
      return { start: `${year}-${pad(month)}-01`, end: null };
    case 'prevMonth': {
      const firstOfThisMonth = `${year}-${pad(month)}-01`;
      const lastOfPrevMonth = shiftDays(firstOfThisMonth, -1);
      return { start: `${lastOfPrevMonth.slice(0, 7)}-01`, end: lastOfPrevMonth };
    }
    case 'ytd':
      return { start: `${year}-01-01`, end: null };
    case 'year':
      // The day after this date last year, through today. Date.UTC rolls Feb 29 over to Mar 1.
      return { start: new Date(Date.UTC(year - 1, month - 1, day + 1)).toISOString().slice(0, 10), end: null };
    default:
      return { start: null, end: null };
  }
};

export const isInTimeFrame = (isoString: string, range: { start: string | null; end: string | null }): boolean => {
  const day = toDayKey(new Date(isoString));
  return (range.start === null || day >= range.start) && (range.end === null || day <= range.end);
};

export const formatDateTime = (isoString: string) => {
  const date = new Date(isoString);
  const { hour, minute, second } = zonedParts(date);
  // Date-only transactions are stored as midnight in APP_TIME_ZONE; don't show a fake time.
  const isDateOnly = hour === '00' && minute === '00' && second === '00';

  return {
    date: date.toLocaleDateString('en-US', {
      timeZone: APP_TIME_ZONE,
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    }),
    time: isDateOnly ? null : date.toLocaleTimeString('en-US', {
      timeZone: APP_TIME_ZONE,
      hour: 'numeric',
      minute: '2-digit',
    }),
  };
};
