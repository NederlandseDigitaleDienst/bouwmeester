import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import type { Casus } from '@/types';
import { CasusAfrondenModal } from './CasusAfrondenModal';

const updateCasus = vi.fn();
vi.mock('@/api/casussen', async (orig) => ({
  ...(await orig<typeof import('@/api/casussen')>()),
  updateCasus: (...args: unknown[]) => updateCasus(...args),
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const CASUS = {
  id: 'c1',
  lead_id: 'l1',
  title: 'Zorgtoeslag',
  fase: 'afronden',
  startvoorwaarden: {},
  team_count: 0,
  issue_count: 0,
  issue_done_count: 0,
  created_at: '2026-10-30T00:00:00Z',
  soorten: [
    { id: 's1', naam: 'Beproeven', kleur: 'groen', eind_eisen: ['Demo gegeven', 'Verslag klaar'] },
    { id: 's2', naam: 'Modelleren', kleur: 'lichtblauw', eind_eisen: [] },
  ],
} as Casus;
const DELEN = { id: 'delen', naam: 'Delen' };

const knop = (tekst: string) => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === tekst)!;

describe('CasusAfrondenModal', () => {
  beforeEach(() => updateCasus.mockReset().mockResolvedValue({ ...CASUS, fase: 'delen' }));

  it('loopt de eindeisen na en zet de fase met de momentopname', async () => {
    const onClose = vi.fn();
    renderWithProviders(
      <ToastProvider>
        <CasusAfrondenModal casus={CASUS} fase={DELEN} onClose={onClose} />
      </ToastProvider>,
    );
    const vinkjes = [...document.querySelectorAll('nldd-checkbox-field')].map((v) => v.getAttribute('label'));
    expect(vinkjes).toEqual(['Demo gegeven', 'Verslag klaar']);
    await act(async () => {
      document
        .querySelector('nldd-checkbox-field[label="Demo gegeven"]')!
        .dispatchEvent(new CustomEvent('change', { detail: { checked: true } }));
    });
    await act(async () => {
      document
        .querySelector('nldd-text-field[accessible-label="Opmerking bij Verslag klaar"]')!
        .dispatchEvent(new CustomEvent('input', { detail: { value: 'Volgende week' } }));
    });
    await act(async () => {
      knop('Naar Delen').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    // Ook wat niet af is gaat mee: het is geen poort.
    expect(updateCasus).toHaveBeenCalledWith('c1', {
      fase: 'delen',
      eind_eisen: [
        { soort_id: 's1', eis: 'Demo gegeven', akkoord: true, opmerking: null },
        { soort_id: 's1', eis: 'Verslag klaar', akkoord: false, opmerking: 'Volgende week' },
      ],
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('begint met wat er eerder is ingevuld, en annuleren verandert niets', async () => {
    const onClose = vi.fn();
    const eerder = {
      ...CASUS,
      eind_eisen: [{ soort_id: 's1', soort: 'Beproeven', eis: 'Verslag klaar', akkoord: true, opmerking: 'Gedeeld' }],
    };
    renderWithProviders(
      <ToastProvider>
        <CasusAfrondenModal casus={eerder} fase={DELEN} onClose={onClose} />
      </ToastProvider>,
    );
    expect(document.querySelector('nldd-checkbox-field[label="Verslag klaar"]')!.hasAttribute('checked')).toBe(true);
    expect(document.querySelector('nldd-checkbox-field[label="Demo gegeven"]')!.hasAttribute('checked')).toBe(false);
    await act(async () => {
      knop('Annuleren').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onClose).toHaveBeenCalled();
    expect(updateCasus).not.toHaveBeenCalled();
  });
});
