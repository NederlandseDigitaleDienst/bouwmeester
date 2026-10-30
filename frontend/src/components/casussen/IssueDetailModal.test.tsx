import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { InitiatiefIdContext } from '@/hooks/useInitiatiefPersonOptions';
import { renderWithProviders } from '@/test/utils';
import { IssueStatus, type BacklogIssue } from '@/types';
import { IssueDetailModal } from './IssueDetailModal';

const updateIssue = vi.fn();
const deleteIssue = vi.fn();
vi.mock('@/api/issues', async (orig) => ({
  ...(await orig<typeof import('@/api/issues')>()),
  updateIssue: (...args: unknown[]) => updateIssue(...args),
  deleteIssue: (...args: unknown[]) => deleteIssue(...args),
}));
vi.mock('@/api/casussen', async (orig) => ({
  ...(await orig<typeof import('@/api/casussen')>()),
  getCasus: async () => ({ id: 'c1', title: 'Zorgtoeslag', dod_items: ['Demo gegeven', 'Verslag af'] }),
  getCasussen: async () => [
    { id: 'c1', title: 'Zorgtoeslag', initiatief_id: 'i1' },
    { id: 'c2', title: 'Subsidieregels', initiatief_id: 'i1' },
    { id: 'c3', title: 'Elders', initiatief_id: 'i2' },
  ],
}));
vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  getInitiatiefPersonen: async () => [{ id: 'p1', naam: 'Lid Een', is_agent: false }],
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const ISSUE = {
  id: 'is1',
  casus_id: 'c1',
  casus: { id: 'c1', title: 'Zorgtoeslag', fase: 'start' },
  title: 'Werkt het?',
  toelichting: '<p>Inclusief het koppelen van data</p>',
  status: IssueStatus.OPEN,
  is_onderzoeksvraag: true,
  assignee_id: null,
  assignee: null,
  sort_order: 0,
  dod_checked: [],
  tasks: [],
  created_at: '2026-10-28T10:00:00Z',
} as unknown as BacklogIssue;

function renderPaneel(onClose = vi.fn()) {
  renderWithProviders(
    <ToastProvider>
      <InitiatiefIdContext.Provider value="i1">
        <IssueDetailModal issue={ISSUE} onClose={onClose} />
      </InitiatiefIdContext.Provider>
    </ToastProvider>,
  );
  return onClose;
}

/** De echte <select> onder een keuzelijst, gevonden aan zijn label. */
const select = (label: string) => document.querySelector<HTMLSelectElement>(`select[aria-label="${label}"]`)!;

const kies = async (el: HTMLSelectElement, value: string) => {
  await act(async () => {
    el.value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
};

const knoppen = (tekst: string) => [...document.querySelectorAll('nldd-button')].filter((b) => b.getAttribute('text') === tekst);
const klik = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
};

describe('IssueDetailModal', () => {
  beforeEach(() => {
    updateIssue.mockReset().mockResolvedValue({ ...ISSUE });
    deleteIssue.mockReset().mockResolvedValue(undefined);
  });

  it('toont de toelichting en slaat een keuze meteen op', async () => {
    renderPaneel();
    expect(document.querySelector('nldd-form-field[label="Toelichting"]')).toBeTruthy();
    await waitFor(() => expect([...select('Issue-eigenaar').options].some((o) => o.text === 'Lid Een')).toBe(true));
    await kies(select('Issue-eigenaar'), 'p1');
    expect(updateIssue).toHaveBeenCalledWith('c1', 'is1', { assignee_id: 'p1' });
  });

  it('biedt alleen casussen van hetzelfde initiatief en verhuist met casus_id', async () => {
    renderPaneel();
    await waitFor(() => expect([...select('Casus').options].map((o) => o.text)).toEqual(['Subsidieregels', 'Zorgtoeslag']));
    await kies(select('Casus'), 'c2');
    expect(updateIssue).toHaveBeenCalledWith('c1', 'is1', { casus_id: 'c2' });
  });

  it('het vinkje maakt er geen onderzoeksvraag van', async () => {
    renderPaneel();
    const vinkje = document.querySelector('nldd-checkbox-field[label="Dit is geen onderzoeksvraag"]')!;
    await act(async () => {
      vinkje.dispatchEvent(new CustomEvent('change', { detail: { checked: true } }));
    });
    expect(updateIssue).toHaveBeenCalledWith('c1', 'is1', { is_onderzoeksvraag: false });
  });

  it('afgerond kiezen loopt via de DoD', async () => {
    const onClose = renderPaneel();
    await kies(select('Status'), IssueStatus.DONE);
    // Eerst de checklist, nog geen status naar de backend.
    expect(updateIssue).not.toHaveBeenCalled();
    await waitFor(() => expect(document.querySelector('nldd-checkbox-field[label="Demo gegeven"]')).toBeTruthy());
    const eis = document.querySelector('nldd-checkbox-field[label="Demo gegeven"]')!;
    await act(async () => {
      eis.dispatchEvent(new CustomEvent('change', { detail: { checked: true } }));
    });
    await klik(knoppen('Afronden met 1 open')[0]);
    expect(updateIssue).toHaveBeenCalledWith('c1', 'is1', { status: IssueStatus.DONE, dod_checked: ['Demo gegeven'] });
    // Het paneel blijft open; alleen de checklist gaat dicht.
    expect(onClose).not.toHaveBeenCalled();
  });

  it('verwijderen vraagt eerst om bevestiging en sluit dan het paneel', async () => {
    const onClose = renderPaneel();
    // De knop onderaan het paneel; de dialoog heeft er ook een, zonder prullenbak.
    await klik(document.querySelector('nldd-button[text="Verwijderen"][start-icon="trash"]')!);
    expect(deleteIssue).not.toHaveBeenCalled();
    expect(document.querySelector('nldd-modal-dialog')!.getAttribute('supporting-text')).toContain(
      'De taken eronder blijven staan',
    );
    const bevestig = knoppen('Verwijderen').find((b) => !b.hasAttribute('start-icon'))!;
    await klik(bevestig);
    expect(deleteIssue).toHaveBeenCalledWith('c1', 'is1');
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
