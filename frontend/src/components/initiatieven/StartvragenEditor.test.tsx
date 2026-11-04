import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act } from '@testing-library/react';

import { renderWithProviders } from '@/test/utils';
import type { InitiatiefDetail, Startvraag } from '@/types';
import { StartvragenEditor } from './StartvragenEditor';

const updateInitiatiefSettings = vi.fn();
vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  updateInitiatiefSettings: (...args: unknown[]) => updateInitiatiefSettings(...args),
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const VRAGEN: Startvraag[] = [
  { id: 'ons_terrein', vraag: 'Is het ons terrein?', antwoordtype: 'ja_nee', opties: [], verplicht: true, op_kaartje: false },
  {
    id: 'casustype',
    vraag: 'Is het een interne casus of een satellietcasus?',
    antwoordtype: 'een_keuze',
    opties: ['Interne casus', 'Satellietcasus'],
    verplicht: true,
    op_kaartje: true,
  },
];

const initiatief = { id: 'i1', naam: 'Init', startvragen: VRAGEN } as unknown as InitiatiefDetail;

const knop = (tekst: string) => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === tekst)!;
const klik = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
};
const typ = async (label: string, tekst: string, enter = false) => {
  const veld = document.querySelector(`nldd-text-field[accessible-label="${label}"]`)!;
  await act(async () => {
    veld.dispatchEvent(new CustomEvent('input', { detail: { value: tekst } }));
  });
  if (enter) {
    await act(async () => {
      veld.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
  }
};

describe('StartvragenEditor', () => {
  beforeEach(() => updateInitiatiefSettings.mockReset().mockResolvedValue({}));

  it('de vaste vraag is niet te verwijderen of te hernoemen', () => {
    renderWithProviders(<StartvragenEditor initiatief={initiatief} />);
    expect(document.querySelector('nldd-icon-button[accessible-label="Vraag 1 verwijderen"]')).toBeTruthy();
    expect(document.querySelector('nldd-icon-button[accessible-label="Vraag 2 verwijderen"]')).toBeNull();
    expect(document.querySelector('nldd-text-field[accessible-label="Vraag 2"]')!.hasAttribute('disabled')).toBe(true);
  });

  it('een keuzevraag toevoegen: opslaan pas met twee keuzes', async () => {
    renderWithProviders(<StartvragenEditor initiatief={initiatief} />);
    expect(knop('Opslaan').hasAttribute('disabled')).toBe(true);
    await klik(knop('Vraag toevoegen'));
    await typ('Vraag 3', 'Via welk kanaal?');
    const select = document.querySelector<HTMLSelectElement>('select[aria-label="Antwoordtype van vraag 3"]')!;
    await act(async () => {
      select.value = 'een_keuze';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(document.body.textContent).toContain('Geef minstens twee keuzes.');
    expect(knop('Opslaan').hasAttribute('disabled')).toBe(true);

    await typ('Nieuwe keuze bij vraag 3', 'Netwerk', true);
    await typ('Nieuwe keuze bij vraag 3', 'Website', true);
    expect(knop('Opslaan').hasAttribute('disabled')).toBe(false);
    await klik(knop('Opslaan'));

    const [, data] = updateInitiatiefSettings.mock.calls[0];
    const nieuw = data.startvragen[2];
    expect(nieuw).toMatchObject({ vraag: 'Via welk kanaal?', antwoordtype: 'een_keuze', opties: ['Netwerk', 'Website'], verplicht: true });
    expect(nieuw.id).toMatch(/^[a-z0-9_]{1,40}$/);
  });

  it('de standaardlijst terugzetten stuurt een lege lijst', async () => {
    renderWithProviders(<StartvragenEditor initiatief={initiatief} />);
    await klik(knop('Standaardlijst terugzetten'));
    expect(updateInitiatiefSettings).toHaveBeenCalledWith('i1', { startvragen: [] });
  });
});
