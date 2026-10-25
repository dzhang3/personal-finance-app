import { describe, expect, it } from 'vitest';
import { getTimeFrameRange, isInTimeFrame, toDayKey } from './dates';

describe('time frame ranges', () => {
  const now = new Date('2024-03-10T17:00:00Z');

  it('starts the week on Sunday in the application time zone', () => {
    expect(getTimeFrameRange('week', now)).toEqual({ start: '2024-03-10', end: null });
  });

  it('includes all calendar days in the previous leap-year month', () => {
    expect(getTimeFrameRange('prevMonth', now)).toEqual({
      start: '2024-02-01',
      end: '2024-02-29',
    });
  });

  it('uses calendar-day boundaries in the application time zone', () => {
    const range = { start: '2024-02-29', end: '2024-02-29' };
    expect(toDayKey(new Date('2024-03-01T04:30:00Z'))).toBe('2024-02-29');
    expect(isInTimeFrame('2024-03-01T04:30:00Z', range)).toBe(true);
    expect(isInTimeFrame('2024-03-01T05:30:00Z', range)).toBe(false);
  });

  it('returns an unbounded range for all time', () => {
    expect(getTimeFrameRange('all', now)).toEqual({ start: null, end: null });
  });
});
