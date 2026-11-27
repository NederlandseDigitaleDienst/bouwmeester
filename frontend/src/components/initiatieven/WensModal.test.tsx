import { describe, it, expect, vi, beforeEach, beforeAll, afterEach } from 'vitest';
import { act, waitFor } from '@testing-library/react';

import { ApiError } from '@/api/client';
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

const melding = () => document.querySelector('nldd-text[role="alert"]')?.textContent ?? '';

describe('WensModal', () => {
  // Met accolades: wat beforeEach teruggeeft, roept vitest na de test aan
  // als opruimfunctie, en mockResolvedValue geeft de mock zelf terug.
  beforeEach(() => {
    updateInitiatiefSettings.mockReset().mockResolvedValue({});
  });
  afterEach(() => vi.useRealTimers());

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

  it('de datum is die van hier, ook vlak na middernacht', async () => {
    // Kwart over twaalf 's nachts, lokale tijd: in UTC is het dan nog gisteren
    // (in Nederland). toISOString zou die datum geven.
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 10, 27, 0, 15));
    renderWithProviders(<WensModal initiatief={initiatief} wens={null} open onClose={vi.fn()} />);
    await typTitel('Na middernacht');
    await klik(knop('Toevoegen'));
    await waitFor(() => expect(updateInitiatiefSettings).toHaveBeenCalledTimes(1));
    expect(updateInitiatiefSettings.mock.calls[0][1].wensen[2].gemeld_op).toBe('2026-11-27');
  });

  it('weigert de backend (422), dan blijft het venster open met de reden erin', async () => {
    updateInitiatiefSettings.mockRejectedValue(
      new ApiError(422, 'Unprocessable Entity', {
        detail: [{ loc: ['body', 'wensen'], type: 'too_long', msg: 'List should have at most 200 items' }],
      }),
    );
    const onClose = vi.fn();
    renderWithProviders(<WensModal initiatief={initiatief} wens={null} open onClose={onClose} />);
    await typTitel('Nog een');
    await klik(knop('Toevoegen'));

    await waitFor(() => expect(melding()).toMatch(/De lijst is vol/));
    expect(onClose).not.toHaveBeenCalled();
    expect(document.querySelector('nldd-text-field')).not.toBeNull();
  });

  it('mislukt verwijderen sluit het bevestigvenster en toont de reden', async () => {
    updateInitiatiefSettings.mockRejectedValue(new ApiError(403, 'Forbidden', { detail: 'Onvoldoende rechten' }));
    const onClose = vi.fn();
    renderWithProviders(<WensModal initiatief={initiatief} wens={BESTAAND} open onClose={onClose} />);
    await klik(verwijderKnoppen()[0]);
    await klik(verwijderKnoppen()[1]);

    await waitFor(() => expect(melding()).toMatch(/eigenaar/));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('een te lange toelichting meldt hij vóór het versturen', async () => {
    const lang = { ...BESTAAND, toelichting: 'x'.repeat(5001) };
    const lijst = { ...initiatief, wensen: [lang, ANDER] } as unknown as InitiatiefDetail;
    renderWithProviders(<WensModal initiatief={lijst} wens={lang} open onClose={vi.fn()} />);
    await klik(knop('Opslaan'));

    expect(melding()).toMatch(/toelichting is te lang/);
    expect(updateInitiatiefSettings).not.toHaveBeenCalled();
  });

  it('dicht toont niets', () => {
    renderWithProviders(<WensModal initiatief={initiatief} wens={null} open={false} onClose={vi.fn()} />);
    expect(document.querySelector('nldd-text-field')).toBeNull();
  });
});
