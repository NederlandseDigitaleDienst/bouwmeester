import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import { IssueAanmakenModal } from './IssueAanmakenModal';

const createIssue = vi.fn();
vi.mock('@/api/issues', async (orig) => ({
  ...(await orig<typeof import('@/api/issues')>()),
  createIssue: (...args: unknown[]) => createIssue(...args),
}));
vi.mock('@/api/casussen', async (orig) => ({
  ...(await orig<typeof import('@/api/casussen')>()),
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

function renderModal(casusId?: string, onClose = vi.fn()) {
  renderWithProviders(
    <ToastProvider>
      <IssueAanmakenModal open onClose={onClose} initiatiefId="i1" casusId={casusId} />
    </ToastProvider>,
  );
  return onClose;
}

const selectMet = (optie: string) =>
  [...document.querySelectorAll('select')].find((s) => [...s.options].some((o) => o.text === optie))!;

const kies = async (select: HTMLSelectElement, value: string) => {
  await act(async () => {
    select.value = value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
};

const typTitel = async (tekst: string) => {
  const veld = document.querySelector('nldd-text-field')!;
  await act(async () => {
    veld.dispatchEvent(new CustomEvent('input', { detail: { value: tekst } }));
  });
};

/** "Dit is geen onderzoeksvraag" aanvinken. */
const geenVraag = async () => {
  const vinkje = document.querySelector('nldd-checkbox-field')!;
  await act(async () => {
    vinkje.dispatchEvent(new CustomEvent('change', { detail: { checked: true } }));
  });
};

const knop = (tekst: string) => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === tekst)!;

const toevoegen = async () => {
  await act(async () => {
    knop('Toevoegen').dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
};

describe('IssueAanmakenModal', () => {
  beforeEach(() => createIssue.mockReset().mockResolvedValue({ id: 'nieuw' }));

  it('is standaard een onderzoeksvraag, met de uitzondering als vinkje eronder', () => {
    renderModal();
    const vinkje = document.querySelector('nldd-checkbox-field')!;
    const titel = document.querySelector('nldd-text-field')!;
    expect(vinkje.getAttribute('label')).toBe('Dit is geen onderzoeksvraag');
    expect(vinkje.hasAttribute('checked')).toBe(false);
    expect(titel.compareDocumentPosition(vinkje) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('maakt standaard een onderzoeksvraag, onder de gekozen casus', async () => {
    const onClose = renderModal();
    await waitFor(() => expect(selectMet('Subsidieregels')).toBeTruthy());
    // Alleen casussen van dit initiatief.
    const casus = selectMet('Subsidieregels');
    expect([...casus.options].filter((o) => o.value).map((o) => o.text)).toEqual(['Subsidieregels', 'Zorgtoeslag']);
    await typTitel('Werkt het?');
    // Zonder casus nog niet toe te voegen.
    expect(knop('Toevoegen').hasAttribute('disabled')).toBe(true);
    await kies(casus, 'c2');
    await toevoegen();
    expect(createIssue).toHaveBeenCalledWith('c2', {
      title: 'Werkt het?',
      is_onderzoeksvraag: true,
      assignee_id: null,
      toelichting: null,
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('het vinkje maakt er geen onderzoeksvraag van; de casus uit het filter staat klaar', async () => {
    renderModal('c1');
    await waitFor(() => expect(selectMet('Zorgtoeslag')).toBeTruthy());
    await typTitel('Schema uitbreiden');
    await geenVraag();
    await toevoegen();
    expect(createIssue).toHaveBeenCalledWith('c1', expect.objectContaining({ title: 'Schema uitbreiden', is_onderzoeksvraag: false }));
  });
});
