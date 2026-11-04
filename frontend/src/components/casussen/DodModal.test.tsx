import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import { IssueStatus } from '@/types';
import { DodModal } from './DodModal';

const updateIssue = vi.fn();
vi.mock('@/api/issues', async (orig) => ({
  ...(await orig<typeof import('@/api/issues')>()),
  updateIssue: (...args: unknown[]) => updateIssue(...args),
}));
vi.mock('@/api/casussen', async (orig) => ({
  ...(await orig<typeof import('@/api/casussen')>()),
  getCasus: async () => ({ id: 'c1', dod_items: ['Getest', 'Gedemonstreerd', 'Gedocumenteerd'] }),
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const ISSUE = { id: 'i1', casus_id: 'c1', title: 'Werkt het?', dod_checked: [] };
const knop = () =>
  [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text')?.startsWith('Afronden'))!;

/** Eén klik zoals nldd-checkbox-field hem meldt: twee keer change, met dezelfde stand. */
const klik = async (label: string, checked: boolean) => {
  const veld = document.querySelector(`nldd-checkbox-field[label="${label}"]`)!;
  await act(async () => {
    veld.dispatchEvent(new CustomEvent('change', { detail: { checked } }));
    veld.dispatchEvent(new CustomEvent('change', { detail: { checked } }));
  });
};

describe('DodModal', () => {
  beforeEach(() => updateIssue.mockReset().mockResolvedValue({ ...ISSUE, status: IssueStatus.DONE }));

  it('houdt een vinkje vast, ook als het veld een klik twee keer meldt', async () => {
    renderWithProviders(
      <ToastProvider>
        <DodModal issue={ISSUE} mode="afronden" onClose={vi.fn()} />
      </ToastProvider>,
    );
    await waitFor(() => expect(document.querySelector('nldd-checkbox-field[label="Getest"]')).toBeTruthy());
    expect(knop().getAttribute('text')).toBe('Afronden met 3 open');

    await klik('Getest', true);
    expect(knop().getAttribute('text')).toBe('Afronden met 2 open');
    await klik('Gedemonstreerd', true);
    expect(knop().getAttribute('text')).toBe('Afronden met 1 open');
    // Uitvinken werkt net zo.
    await klik('Getest', false);
    expect(knop().getAttribute('text')).toBe('Afronden met 2 open');

    await act(async () => {
      knop().dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(updateIssue).toHaveBeenCalledWith('c1', 'i1', { status: IssueStatus.DONE, dod_checked: ['Gedemonstreerd'] });
  });
});
