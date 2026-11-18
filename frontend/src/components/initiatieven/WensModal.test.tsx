import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/utils';
import type { InitiatiefDetail, Wens } from '@/types';
import { WensModal } from './WensModal';

const updateInitiatiefSettings = vi.fn();
vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  updateInitiatiefSettings: (...args: unknown[]) => updateInitiatiefSettings(...args),
}));
vi.mock('@/contexts/CurrentPersonContext', () => ({
  useCurrentPerson: () => ({ currentPerson: { id: 'p1', naam: 'Melder Een' } }),
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const BESTAAND: Wens = {
  id: 'w1',
  soort: 'suggestie',
  titel: 'Vaste werktypes',
  toelichting: null,
  gemeld_door: 'Melder Twee',
  gemeld_op: '2026-11-05',
};
const ANDER: Wens = { id: 'w2', soort: 'bug', titel: 'Bord vergeet de volgorde' };

const initiatief = { id: 'i1', naam: 'Init', wensen: [BESTAAND, ANDER] } as unknown as InitiatiefDetail;

const knop = (tekst: string) => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === tekst)!;
const klik = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
};
const verwijderKnoppen = () =>
  [...document.querySelectorAll('nldd-button')].filter((b) => b.getAttribute('text') === 'Verwijderen');
const typTitel = async (tekst: string) => {
  const veld = document.querySelector('nldd-text-field')!;
  await act(async () => {
    veld.dispatchEvent(new CustomEvent('input', { detail: { value: tekst } }));
  });
};
const kiesSoort = async (soort: Wens['soort']) => {
  const keuze = document.querySelector('nldd-segmented-control[accessible-label="Soort wens"]')!;
  await act(async () => {
    keuze.dispatchEvent(new CustomEvent('change', { detail: { value: soort } }));
  });
};

describe('WensModal', () => {
  beforeEach(() => updateInitiatiefSettings.mockReset().mockResolvedValue({}));

  it('een nieuwe wens komt achteraan, met naam en datum van de melder', async () => {
    const onClose = vi.fn();
    renderWithProviders(<WensModal initiatief={initiatief} wens={null} open onClose={onClose} />);
    expect(knop('Toevoegen').hasAttribute('disabled')).toBe(true);
    // Alleen de knop van het (dichte) bevestigvenster, niet die in de voet.
    expect(verwijderKnoppen()).toHaveLength(1);

    await kiesSoort('bug');
    await typTitel('  Filter springt terug  ');
    await klik(knop('Toevoegen'));

    await waitFor(() => expect(updateInitiatiefSettings).toHaveBeenCalledTimes(1));
    const [id, data] = updateInitiatiefSettings.mock.calls[0];
    expect(id).toBe('i1');
    expect(data.wensen.slice(0, 2)).toEqual([BESTAAND, ANDER]);
    const nieuw = data.wensen[2];
    expect(nieuw).toMatchObject({ soort: 'bug', titel: 'Filter springt terug', toelichting: null, gemeld_door: 'Melder Een' });
    expect(nieuw.id).toBeTruthy();
    expect(nieuw.gemeld_op).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('bewerken houdt id, melder en plek; de rest van de lijst blijft', async () => {
    renderWithProviders(<WensModal initiatief={initiatief} wens={BESTAAND} open onClose={vi.fn()} />);
    await typTitel('Vaste werktypes per casus');
    await klik(knop('Opslaan'));

    await waitFor(() => expect(updateInitiatiefSettings).toHaveBeenCalledTimes(1));
    const [, data] = updateInitiatiefSettings.mock.calls[0];
    expect(data.wensen).toEqual([{ ...BESTAAND, titel: 'Vaste werktypes per casus', toelichting: null }, ANDER]);
  });

  it('verwijderen vraagt eerst om bevestiging en haalt alleen die wens weg', async () => {
    renderWithProviders(<WensModal initiatief={initiatief} wens={BESTAAND} open onClose={vi.fn()} />);
    expect(verwijderKnoppen()).toHaveLength(2);
    await klik(verwijderKnoppen()[0]);
    expect(updateInitiatiefSettings).not.toHaveBeenCalled();

    // Het bevestigvenster heeft zijn eigen knop Verwijderen, als laatste.
    await klik(verwijderKnoppen()[1]);

    await waitFor(() => expect(updateInitiatiefSettings).toHaveBeenCalledTimes(1));
    expect(updateInitiatiefSettings.mock.calls[0][1].wensen).toEqual([ANDER]);
  });

  it('dicht toont niets', () => {
    renderWithProviders(<WensModal initiatief={initiatief} wens={null} open={false} onClose={vi.fn()} />);
    expect(document.querySelector('nldd-text-field')).toBeNull();
  });
});
