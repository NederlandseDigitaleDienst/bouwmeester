import { describe, it, expect, vi, beforeAll } from 'vitest';
import { waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import type { CasusDetail } from '@/types';
import { CasusInfo } from './CasusInfo';

let accessLevel = 'contributor';
vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  getInitiatief: async () => ({
    id: 'i1',
    naam: 'Init',
    access_level: accessLevel,
    casus_fases: [
      { id: 'start', naam: 'Start', kleur: 'lintblauw' },
      { id: 'uitvoeren', naam: 'Uitvoeren', kleur: 'oranje' },
    ],
  }),
}));
vi.mock('@/api/casusSoorten', async (orig) => ({
  ...(await orig<typeof import('@/api/casusSoorten')>()),
  getCasusSoorten: async () => [],
}));
vi.mock('@/contexts/CurrentPersonContext', () => ({ useCurrentPerson: () => ({ currentPerson: { id: 'p1' } }) }));
vi.mock('@/contexts/LeadDetailContext', () => ({ useLeadDetail: () => ({ openLeadDetail: vi.fn() }) }));
// Het Mattermost-blok heeft eigen tests; hier alleen of het mag beheren.
vi.mock('@/components/mattermost/MattermostChannelsSection', () => ({
  MattermostChannelsSection: ({ kanBeheren }: { kanBeheren: boolean }) => <div data-kanaal-beheren={String(kanBeheren)} />,
}));
vi.mock('@/components/mattermost/CasusKanaalberichten', () => ({ CasusKanaalberichten: () => null }));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const CASUS = {
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
  koelkast_verwacht_terug: '2026-11-21',
  soorten: [],
  team: [],
  dod_items: [],
  lead: { id: 'l1', title: 'Lead', stage: 'in_the_pocket' },
} as CasusDetail;

const knop = (tekst: string) => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === tekst);
const faseLijst = () => [...document.querySelectorAll('select')].find((s) => [...s.options].some((o) => o.text === 'Uitvoeren'));

function render(casus: CasusDetail = CASUS) {
  renderWithProviders(
    <ToastProvider>
      <CasusInfo casus={casus} />
    </ToastProvider>,
  );
}

describe('CasusInfo en de koelkast', () => {
  it('zet de fase vast in de koelkast, met uitleg', async () => {
    accessLevel = 'contributor';
    render();
    await waitFor(() => expect(knop('Uit de koelkast')).toBeTruthy());
    expect(faseLijst()!.disabled).toBe(true);
    expect(document.body.textContent).toContain('De fase staat vast zolang de casus in de koelkast staat.');
    // Een verlopen datum kort aangeduid.
    expect(document.body.textContent).toContain('(datum voorbij)');
  });

  it('buiten de koelkast is de fase vrij', async () => {
    accessLevel = 'contributor';
    render({ ...CASUS, koelkast_sinds: null, koelkast_reden: null, koelkast_verwacht_terug: null });
    await waitFor(() => expect(knop('In de koelkast zetten')).toBeTruthy());
    expect(faseLijst()!.disabled).toBe(false);
    expect(document.body.textContent).not.toContain('De fase staat vast');
  });

  it('een kijker ziet waarom hij stilligt, maar geen knoppen', async () => {
    accessLevel = 'viewer';
    render();
    // Wachten tot het initiatief er is (de fasenamen), anders zegt het niets.
    await waitFor(() => expect(faseLijst()).toBeTruthy());
    expect(document.body.textContent).toContain('Partner heeft geen tijd');
    expect(knop('Uit de koelkast')).toBeUndefined();
    expect(knop('Reden of datum aanpassen')).toBeUndefined();
    expect(document.querySelector('[data-kanaal-beheren="false"]')).toBeTruthy();
  });

  it('een kijker zet niets in de koelkast', async () => {
    accessLevel = 'viewer';
    render({ ...CASUS, koelkast_sinds: null, koelkast_reden: null, koelkast_verwacht_terug: null });
    await waitFor(() => expect(faseLijst()).toBeTruthy());
    expect(knop('In de koelkast zetten')).toBeUndefined();
  });

  it('een trekker die alleen kijker is, krijgt de knoppen wel', async () => {
    accessLevel = 'viewer';
    render({
      ...CASUS,
      team: [{ id: 'rp1', person_id: 'p1', person_naam: 'Trekker', rol: 'trekker' }],
    } as CasusDetail);
    await waitFor(() => expect(document.querySelector('[data-kanaal-beheren="true"]')).toBeTruthy());
    expect(knop('Uit de koelkast')).toBeTruthy();
  });
});
