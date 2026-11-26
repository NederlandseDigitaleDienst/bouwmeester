import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, fireEvent, waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import type { Casus, CasusFaseDef } from '@/types';
import { CasusFunnelBord } from './CasusFunnelBord';

const updateCasus = vi.fn();
const haalUitKoelkast = vi.fn();
vi.mock('@/api/casussen', async (orig) => ({
  ...(await orig<typeof import('@/api/casussen')>()),
  updateCasus: (...args: unknown[]) => updateCasus(...args),
  haalUitKoelkast: (...args: unknown[]) => haalUitKoelkast(...args),
}));

const FASES: CasusFaseDef[] = [
  { id: 'start', naam: 'Start', kleur: 'lintblauw' },
  { id: 'uitvoeren', naam: 'Uitvoeren', kleur: 'oranje' },
  { id: 'besluiten', naam: 'Besluiten', kleur: 'mosgroen' },
];
vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  getInitiatief: async () => ({ id: 'i1', naam: 'Init', casus_fases: FASES, startvragen: [] }),
}));
vi.mock('@/hooks/useLeads', () => ({ useLeads: () => ({ data: [] }) }));
// Het kaartje en het startvenster doen hier niet mee.
vi.mock('./CasusCard', () => ({ CasusCard: ({ casus }: { casus: Casus }) => <div>{casus.title}</div> }));
vi.mock('./StartCasusModal', () => ({ StartCasusModal: () => null }));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const IN_KOELKAST = {
  id: 'c1',
  lead_id: 'l1',
  initiatief_id: 'i1',
  title: 'Zorgtoeslag',
  fase: 'uitvoeren',
  startvoorwaarden: {},
  team_count: 0,
  issue_count: 0,
  issue_done_count: 0,
  created_at: '2026-10-30T00:00:00Z',
  koelkast_sinds: '2026-11-20T09:00:00Z',
  koelkast_reden: 'Partner heeft geen tijd',
  koelkast_verwacht_terug: '2027-01-15',
  soorten: [{ id: 's1', naam: 'Beproeven', kleur: 'groen', eind_eisen: ['Demo gegeven'] }],
} as Casus;

const knop = (tekst: string) => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === tekst);
const klik = (tekst: string) =>
  act(async () => {
    knop(tekst)!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });

/** Sleep een kaartje naar de kolom met deze naam. */
const sleepNaar = async (kolom: string, casusId = 'c1') => {
  const tag = await waitFor(() => {
    const t = document.querySelector(`nldd-tag[text="${kolom}"]`);
    expect(t).toBeTruthy();
    return t!;
  });
  await act(async () => {
    fireEvent.drop(tag.closest('div')!, { dataTransfer: { getData: () => casusId } });
  });
};

function render(casus: Casus = IN_KOELKAST) {
  renderWithProviders(
    <ToastProvider>
      <CasusFunnelBord casussen={[casus]} initiatiefId="i1" onOpen={vi.fn()} />
    </ToastProvider>,
  );
}

describe('CasusFunnelBord en de koelkast', () => {
  beforeEach(() => {
    updateCasus.mockReset().mockResolvedValue({ ...IN_KOELKAST, koelkast_sinds: null });
    haalUitKoelkast.mockReset().mockResolvedValue({ ...IN_KOELKAST, koelkast_sinds: null });
  });

  it('haalt hem in één wijziging uit de koelkast en naar de andere fase', async () => {
    render();
    await sleepNaar('Start');
    expect(updateCasus).toHaveBeenCalledWith('c1', { fase: 'start', uit_koelkast: true });
    expect(haalUitKoelkast).not.toHaveBeenCalled();
  });

  it('terug naar zijn eigen fase: alleen uit de koelkast', async () => {
    render();
    await sleepNaar('Uitvoeren');
    expect(haalUitKoelkast).toHaveBeenCalledWith('c1');
    expect(updateCasus).not.toHaveBeenCalled();
  });

  it('naar de laatste fase eerst het afrondvenster; annuleren laat hem in de koelkast', async () => {
    render();
    await sleepNaar('Besluiten');
    // Nog niets gewijzigd: eerst de eindeisen.
    await waitFor(() => expect(knop('Naar Besluiten')).toBeTruthy());
    expect(document.body.textContent).toContain('Hij gaat daarmee ook uit de koelkast.');
    expect(updateCasus).not.toHaveBeenCalled();
    expect(haalUitKoelkast).not.toHaveBeenCalled();
    await klik('Annuleren');
    expect(knop('Naar Besluiten')).toBeUndefined();
    expect(updateCasus).not.toHaveBeenCalled();
    expect(haalUitKoelkast).not.toHaveBeenCalled();

    // Nog eens, en nu afronden: fase, eindeisen en uit de koelkast in één.
    await sleepNaar('Besluiten');
    await waitFor(() => expect(knop('Naar Besluiten')).toBeTruthy());
    await klik('Naar Besluiten');
    expect(updateCasus).toHaveBeenCalledTimes(1);
    expect(updateCasus).toHaveBeenCalledWith('c1', {
      fase: 'besluiten',
      eind_eisen: [{ soort_id: 's1', eis: 'Demo gegeven', akkoord: false, opmerking: null }],
      uit_koelkast: true,
    });
    expect(haalUitKoelkast).not.toHaveBeenCalled();
  });

  it('buiten de koelkast gaat uit_koelkast niet mee', async () => {
    render({ ...IN_KOELKAST, koelkast_sinds: null, koelkast_reden: null, koelkast_verwacht_terug: null });
    await sleepNaar('Start');
    expect(updateCasus).toHaveBeenCalledWith('c1', { fase: 'start' });
  });
});
