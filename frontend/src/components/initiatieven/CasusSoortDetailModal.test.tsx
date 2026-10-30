import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import type { CasusSoort } from '@/types';
import { CasusSoortDetailModal } from './CasusSoortDetailModal';

const updateCasusSoort = vi.fn();
vi.mock('@/api/casusSoorten', async (orig) => ({
  ...(await orig<typeof import('@/api/casusSoorten')>()),
  updateCasusSoort: (...args: unknown[]) => updateCasusSoort(...args),
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const SOORT: CasusSoort = {
  id: 's1',
  naam: 'Beproeven',
  kleur: 'groen',
  uitleg: 'We proberen het uit bij een partner.',
  initiatief_id: 'i1',
  sort_order: 0,
  casus_count: 0,
  created_at: '2026-10-29T00:00:00Z',
  hoe_ver: null,
  start_eisen: ['Partner gevonden'],
  eind_eisen: [],
};

const knoppen = (tekst: string) => [...document.querySelectorAll('nldd-button')].filter((b) => b.getAttribute('text') === tekst);
const knop = (tekst: string) => knoppen(tekst)[0];

describe('CasusSoortDetailModal', () => {
  beforeEach(() => updateCasusSoort.mockReset().mockResolvedValue({ ...SOORT }));

  it('toont de bestaande eisen en slaat een nieuwe eindeis op', async () => {
    const onClose = vi.fn();
    renderWithProviders(
      <ToastProvider>
        <CasusSoortDetailModal soort={SOORT} initiatiefId="i1" onClose={onClose} />
      </ToastProvider>,
    );
    expect(document.querySelector('nldd-text-field[accessible-label="Starteis 1"]')).toBeTruthy();
    const nieuw = document.querySelector('nldd-text-field[accessible-label="Nieuwe eindeis"]')!;
    await act(async () => {
      nieuw.dispatchEvent(new CustomEvent('input', { detail: { value: 'Demo gegeven' } }));
    });
    // Twee lijsten, twee knoppen Toevoegen: de tweede hoort bij de eindeisen.
    await act(async () => {
      knoppen('Toevoegen')[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await act(async () => {
      knop('Opslaan').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(updateCasusSoort).toHaveBeenCalledWith('i1', 's1', {
      uitleg: 'We proberen het uit bij een partner.',
      hoe_ver: null,
      start_eisen: ['Partner gevonden'],
      eind_eisen: ['Demo gegeven'],
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('toont niets zonder soort', () => {
    renderWithProviders(
      <ToastProvider>
        <CasusSoortDetailModal soort={null} initiatiefId="i1" onClose={vi.fn()} />
      </ToastProvider>,
    );
    expect(document.querySelector('nldd-window')).toBeNull();
  });
});
