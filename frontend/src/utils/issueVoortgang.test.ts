import { describe, it, expect } from 'vitest';
import { TaskStatus } from '@/types';
import { allesAfNa } from './issueVoortgang';

const t = (id: string, status: TaskStatus) => ({ id, status });

describe('allesAfNa', () => {
  it('de laatste open taak naar afgerond: alles af', () => {
    expect(allesAfNa([t('a', TaskStatus.DONE), t('b', TaskStatus.IN_PROGRESS)], 'b', TaskStatus.DONE)).toBe(true);
  });
  it('er staat nog een taak open: niet alles af', () => {
    expect(allesAfNa([t('a', TaskStatus.OPEN), t('b', TaskStatus.IN_PROGRESS)], 'b', TaskStatus.DONE)).toBe(false);
  });
  it('naar een andere kolom dan afgerond: nooit', () => {
    expect(allesAfNa([t('a', TaskStatus.DONE), t('b', TaskStatus.OPEN)], 'b', TaskStatus.IN_PROGRESS)).toBe(false);
  });
  it('geannuleerde taken tellen niet mee', () => {
    expect(allesAfNa([t('a', TaskStatus.CANCELLED), t('b', TaskStatus.OPEN)], 'b', TaskStatus.DONE)).toBe(true);
  });
  it('alleen geannuleerde taken over: niets af te ronden', () => {
    expect(allesAfNa([t('a', TaskStatus.CANCELLED)], 'x', TaskStatus.DONE)).toBe(false);
  });
});
