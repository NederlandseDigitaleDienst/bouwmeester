import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { act } from '@testing-library/react';

import { renderWithProviders } from '@/test/utils';
import type { InitiatiefDetail, Wens } from '@/types';
import { InitiatiefRegelRitme } from './InitiatiefRegelRitme';

vi.mock('@/hooks/useCasusSoorten', () => ({ useCasusSoorten: () => ({ data: [] }) }));
vi.mock('@/hooks/useLeadColumns', () => ({ useLeadColumns: () => ({ columns: [] }) }));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});
afterEach(() => vi.restoreAllMocks());

const doc = (tekst: string) =>
  JSON.stringify({ type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: tekst }] }] });

const MET_TOELICHTING: Wens = {
  id: 'w1',
  soort: 'bug',
  titel: 'Bord vergeet de volgorde',
  toelichting: doc('Na herladen staat de volgorde weer op datum.'),
  gemeld_door: 'Melder Een',
  gemeld_op: '2026-11-05',
};
const ZONDER: Wens = { id: 'w2', soort: 'suggestie', titel: 'Vaste werktypes' };
const MET_HTML: Wens = { id: 'w3', soort: 'bug', titel: 'Opmaak', toelichting: '<img src="x" onerror="alert(1)"> zie plaatje' };

const initiatief = (access_level: InitiatiefDetail['access_level']) =>
  ({
    id: 'i1',
    naam: 'Init',
    access_level,
    casus_fases: [],
    dod_items: ['Getoetst', 'Getoetst'],
    wensen: [MET_TOELICHTING, ZONDER, MET_HTML],
  }) as unknown as InitiatiefDetail;

/** Het kaartje Wensen voor Bouwmeester openklappen. */
const openWensen = async () => {
  const kop = [...document.querySelectorAll('h3 button')].find((b) => b.textContent?.includes('Wensen voor Bouwmeester'))!;
  await act(async () => {
    (kop as HTMLButtonElement).click();
  });
};
const wensKnop = (titel: string) =>
  [...document.querySelectorAll('button.plain-button[aria-expanded]')].find((b) => b.textContent?.includes(titel)) as
    | HTMLButtonElement
    | undefined;
const potloden = () => document.querySelectorAll('nldd-icon-button[icon="pencil"]');

describe('InitiatiefRegelRitme, wensen', () => {
  it('een lid klapt de toelichting open en leest hem, zonder te kunnen bewerken', async () => {
    renderWithProviders(<InitiatiefRegelRitme initiatief={initiatief('contributor')} />);
    await openWensen();

    const knop = wensKnop('Bord vergeet de volgorde')!;
    expect(knop.getAttribute('aria-expanded')).toBe('false');
    expect(document.body.textContent).not.toContain('Na herladen');

    await act(async () => knop.click());
    expect(knop.getAttribute('aria-expanded')).toBe('true');
    expect(document.body.textContent).toContain('Na herladen staat de volgorde weer op datum.');

    // Geen potlood, geen regel die als knop het venster opent.
    expect(potloden()).toHaveLength(0);
    expect(document.querySelector('[role="button"]')).toBeNull();
    expect(document.body.textContent).not.toContain('Wens bewerken');
  });

  it('een wens zonder toelichting is geen knop', async () => {
    renderWithProviders(<InitiatiefRegelRitme initiatief={initiatief('viewer')} />);
    await openWensen();
    expect(document.body.textContent).toContain('Vaste werktypes');
    expect(wensKnop('Vaste werktypes')).toBeUndefined();
  });

  it('HTML in een toelichting wordt tekst, geen element', async () => {
    renderWithProviders(<InitiatiefRegelRitme initiatief={initiatief('viewer')} />);
    await openWensen();
    await act(async () => wensKnop('Opmaak')!.click());
    expect(document.body.textContent).toContain('zie plaatje');
    expect(document.querySelector('img')).toBeNull();
  });

  it('de eigenaar heeft per wens een potlood dat het venster opent', async () => {
    renderWithProviders(<InitiatiefRegelRitme initiatief={initiatief('eigenaar')} />);
    await openWensen();
    expect(potloden()).toHaveLength(3);
    expect(potloden()[0].getAttribute('accessible-label')).toBe('Bord vergeet de volgorde: bewerken');

    await act(async () => {
      potloden()[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(document.querySelector('nldd-text-field')).not.toBeNull();
  });
});

describe('InitiatiefRegelRitme, de rest', () => {
  it('twee gelijke regels in de DoD geven geen dubbele key', () => {
    const fout = vi.spyOn(console, 'error').mockImplementation(() => {});
    renderWithProviders(<InitiatiefRegelRitme initiatief={initiatief('viewer')} />);
    const dod = [...document.querySelectorAll('h3 button')].find((b) => b.textContent?.includes('DoD'))! as HTMLButtonElement;
    act(() => dod.click());
    expect(fout.mock.calls.some((c) => String(c[0]).includes('same key'))).toBe(false);
  });

  it('noemt geen initiatief bij naam in de vaste uitleg', async () => {
    renderWithProviders(<InitiatiefRegelRitme initiatief={initiatief('viewer')} />);
    const kop = [...document.querySelectorAll('h3 button')].find((b) => b.textContent?.includes('Wie en wat'))! as HTMLButtonElement;
    await act(async () => kop.click());
    const begrippen = document.querySelector('nldd-list[accessible-label="Begrippen"]')!;
    const uitleg = [...begrippen.querySelectorAll('nldd-title-cell')].map((c) => c.getAttribute('supporting-text')).join(' ');
    expect(uitleg).toContain('casusteam');
    expect(uitleg).not.toMatch(/RegelRecht/);
  });
});
