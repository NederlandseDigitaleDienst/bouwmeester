import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import type { CasusSoort, Lead, Startvraag } from '@/types';
import { StartCasusModal } from './StartCasusModal';

const startCasus = vi.fn();
vi.mock('@/api/casussen', async (orig) => ({
  ...(await orig<typeof import('@/api/casussen')>()),
  startCasus: (...args: unknown[]) => startCasus(...args),
}));
const criteriaVanInitiatief = vi.fn(() => [] as string[]);
/** De standaardlijst zoals de backend hem geeft. */
const STANDAARD: Startvraag[] = [
  { id: 'ons_terrein', vraag: 'Is het ons terrein?', antwoordtype: 'ja_nee', opties: [], verplicht: true, op_kaartje: false },
  {
    id: 'casustype',
    vraag: 'Is het een interne casus of een satellietcasus?',
    antwoordtype: 'een_keuze',
    opties: ['Interne casus', 'Satellietcasus'],
    verplicht: true,
    op_kaartje: true,
  },
  {
    id: 'schakels',
    vraag: 'Op welke schakels maken we impact?',
    antwoordtype: 'meer_keuzes',
    opties: ['Uitvoeringstoets', 'Publiceren', 'Regelbeheer'],
    verplicht: true,
    op_kaartje: false,
  },
  {
    id: 'hoever',
    vraag: 'Tot hoever brengen we het?',
    antwoordtype: 'een_keuze',
    opties: ['Verkennen', 'Beproeven met een partner'],
    verplicht: true,
    op_kaartje: true,
  },
];
const vragenVanInitiatief = vi.fn(() => STANDAARD);
vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  getInitiatiefPersonen: async () => [],
  getInitiatief: async () => ({
    id: 'i1',
    naam: 'Init',
    acceptatiecriteria: criteriaVanInitiatief(),
    startvragen: vragenVanInitiatief(),
  }),
}));

const soortenVanInitiatief = vi.fn(() => [] as CasusSoort[]);
vi.mock('@/api/casusSoorten', async (orig) => ({
  ...(await orig<typeof import('@/api/casusSoorten')>()),
  getCasusSoorten: async () => soortenVanInitiatief(),
}));
const soort = (id: string, naam: string, start_eisen: string[]): CasusSoort => ({
  id,
  naam,
  kleur: 'groen',
  uitleg: null,
  start_eisen,
  eind_eisen: [],
  initiatief_id: 'i1',
  sort_order: 0,
  casus_count: 0,
  created_at: '2026-10-30T00:00:00Z',
});

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const lead = (id: string, title: string) => ({ id, title, organization: null, initiatief_id: 'i1' }) as unknown as Lead;

/** De echte <select> onder een keuzelijst, gevonden aan een van zijn opties. */
const selectMet = (optie: string) =>
  [...document.querySelectorAll('select')].find((s) => [...s.options].some((o) => o.text === optie))!;

const kies = async (select: HTMLSelectElement, value: string) => {
  await act(async () => {
    select.value = value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
};

/** Een vinkje aan- of uitzetten: nldd-checkbox-field meldt dat met detail.checked. */
const vink = async (label: string, checked = true) => {
  const veld = document.querySelector(`nldd-checkbox-field[label="${label}"]`)!;
  await act(async () => {
    veld.dispatchEvent(new CustomEvent('change', { detail: { checked } }));
  });
};

const startknop = () => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === 'Casus starten')!;

describe('StartCasusModal vanuit het casusbord', () => {
  beforeEach(() => {
    startCasus.mockReset().mockResolvedValue({ id: 'c9', fase: 'start' });
    criteriaVanInitiatief.mockReturnValue([]);
    vragenVanInitiatief.mockReturnValue(STANDAARD);
    soortenVanInitiatief.mockReturnValue([]);
  });

  it('loopt de starteisen van de gekozen soorten na, met een opmerking per eis', async () => {
    soortenVanInitiatief.mockReturnValue([
      soort('s1', 'Beproeven', ['Partner gevonden', 'Data beschikbaar']),
      soort('s2', 'Modelleren', []),
    ]);
    renderWithProviders(
      <ToastProvider>
        <StartCasusModal lead={null} kiesUit={[lead('l1', 'Lead een')]} open onClose={vi.fn()} />
      </ToastProvider>,
    );
    const eis = (label: string) => document.querySelector(`nldd-checkbox-field[label="${label}"]`);
    await waitFor(() => expect(eis('Beproeven')).toBeTruthy());
    // Zonder gekozen soort geen starteisen; een soort zonder eisen voegt niets toe.
    await vink('Modelleren');
    expect(eis('Partner gevonden')).toBeNull();
    await vink('Beproeven');
    await waitFor(() => expect(eis('Partner gevonden')).toBeTruthy());
    await vink('Partner gevonden');
    const opmerking = document.querySelector('nldd-text-field[accessible-label="Opmerking bij Data beschikbaar"]')!;
    await act(async () => {
      opmerking.dispatchEvent(new CustomEvent('input', { detail: { value: 'Volgt in november' } }));
    });
    await kies(selectMet('Lead een'), 'l1');
    await kies(selectMet('Ja'), 'ja');
    await kies(selectMet('Interne casus'), 'intern');
    await kies(selectMet('Verkennen'), 'Verkennen');
    await vink('Publiceren');
    await act(async () => {
      startknop().dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    // Ook wat niet is afgevinkt gaat mee: de lijst is geen poort.
    expect(startCasus).toHaveBeenCalledWith(
      expect.objectContaining({
        soort_ids: ['s1', 's2'],
        startvoorwaarden: expect.objectContaining({
          start_eisen: [
            { soort_id: 's1', eis: 'Partner gevonden', akkoord: true, opmerking: null },
            { soort_id: 's1', eis: 'Data beschikbaar', akkoord: false, opmerking: 'Volgt in november' },
          ],
        }),
      }),
    );
  });

  it('kiest uit de leads die klaarstaan en start pas als alles is ingevuld', async () => {
    const onStarted = vi.fn();
    renderWithProviders(
      <ToastProvider>
        <StartCasusModal lead={null} kiesUit={[lead('l1', 'Lead een'), lead('l2', 'Lead twee')]} open onClose={vi.fn()} onStarted={onStarted} />
      </ToastProvider>,
    );
    const leads = selectMet('Lead een');
    expect([...leads.options].map((o) => o.text)).toEqual(['Kies een lead', 'Lead een', 'Lead twee']);
    expect(startknop().hasAttribute('disabled')).toBe(true);

    // Eerst de vragen, dan de lead: de antwoorden blijven staan.
    await waitFor(() => expect(selectMet('Verkennen')).toBeTruthy());
    await kies(selectMet('Ja'), 'ja');
    await kies(selectMet('Interne casus'), 'intern');
    await kies(selectMet('Verkennen'), 'Verkennen');
    expect(startknop().hasAttribute('disabled')).toBe(true);
    await kies(leads, 'l2');
    // Zonder schakel nog niet: minstens één is verplicht.
    expect(startknop().hasAttribute('disabled')).toBe(true);
    await vink('Regelbeheer');
    await vink('Uitvoeringstoets');
    expect(startknop().hasAttribute('disabled')).toBe(false);

    await act(async () => {
      startknop().dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(startCasus).toHaveBeenCalledWith(
      expect.objectContaining({
        lead_id: 'l2',
        // De schakels in de volgorde van de lijst, niet van het aanvinken.
        startvoorwaarden: {
          casustype: 'intern',
          antwoorden: [
            { vraag_id: 'ons_terrein', waarde: true },
            { vraag_id: 'schakels', waarde: ['Uitvoeringstoets', 'Regelbeheer'] },
            { vraag_id: 'hoever', waarde: 'Verkennen' },
          ],
          toelichting: null,
        },
      }),
    );
    expect(onStarted).toHaveBeenCalledWith(expect.objectContaining({ id: 'c9' }));
  });

  it('vraagt bij een satellietcasus de acceptatiecriteria na, met een uitleg per criterium', async () => {
    criteriaVanInitiatief.mockReturnValue(['Data beschikbaar', 'Partner gevonden']);
    renderWithProviders(
      <ToastProvider>
        <StartCasusModal lead={null} kiesUit={[lead('l1', 'Lead een')]} open onClose={vi.fn()} />
      </ToastProvider>,
    );
    // De vinkjes van de criteria; die van de schakels staan er altijd.
    const criteriumVinkjes = () =>
      [...document.querySelectorAll('nldd-checkbox-field')].filter((el) =>
        ['Data beschikbaar', 'Partner gevonden'].includes(el.getAttribute('label') ?? ''),
      );
    // Bij een interne casus geen criteria; pas bij een satellietcasus.
    await waitFor(() => expect(selectMet('Satellietcasus')).toBeTruthy());
    await kies(selectMet('Satellietcasus'), 'intern');
    await new Promise((r) => setTimeout(r, 20));
    expect(criteriumVinkjes().length).toBe(0);
    await kies(selectMet('Satellietcasus'), 'satelliet');
    await waitFor(() => expect(criteriumVinkjes().length).toBe(2));
    const [data] = criteriumVinkjes();
    expect(data.getAttribute('label')).toBe('Data beschikbaar');
    await act(async () => {
      data.dispatchEvent(new CustomEvent('change', { detail: { checked: true } }));
    });
    const uitleg = document.querySelector('nldd-text-field[accessible-label="Uitleg bij Data beschikbaar"]')!;
    await act(async () => {
      uitleg.dispatchEvent(new CustomEvent('input', { detail: { value: 'Via CBS' } }));
    });
    await kies(selectMet('Lead een'), 'l1');
    await kies(selectMet('Ja'), 'ja');
    await kies(selectMet('Verkennen'), 'Verkennen');
    await vink('Publiceren');
    await act(async () => {
      startknop().dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(startCasus).toHaveBeenCalledWith(
      expect.objectContaining({
        startvoorwaarden: expect.objectContaining({
          casustype: 'satelliet',
          acceptatiecriteria: [
            { criterium: 'Data beschikbaar', akkoord: true, opmerking: 'Via CBS' },
            { criterium: 'Partner gevonden', akkoord: false, opmerking: null },
          ],
        }),
      }),
    );
  });

  it('stelt de eigen vragen van het initiatief, een vrije vraag hoeft niet', async () => {
    vragenVanInitiatief.mockReturnValue([
      STANDAARD[1],
      { id: 'kanaal', vraag: 'Via welk kanaal?', antwoordtype: 'een_keuze', opties: ['Netwerk', 'Website'], verplicht: true, op_kaartje: false },
      { id: 'notitie', vraag: 'Nog iets?', antwoordtype: 'vrij', opties: [], verplicht: false, op_kaartje: false },
    ]);
    renderWithProviders(
      <ToastProvider>
        <StartCasusModal lead={null} kiesUit={[lead('l1', 'Lead een')]} open onClose={vi.fn()} />
      </ToastProvider>,
    );
    await waitFor(() => expect(selectMet('Website')).toBeTruthy());
    // De standaardvragen staan er niet bij.
    expect(document.body.textContent).not.toContain('Tot hoever');
    await kies(selectMet('Lead een'), 'l1');
    await kies(selectMet('Interne casus'), 'intern');
    await kies(selectMet('Website'), 'Website');
    expect(startknop().hasAttribute('disabled')).toBe(false);
    await act(async () => {
      startknop().dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(startCasus).toHaveBeenCalledWith(
      expect.objectContaining({
        startvoorwaarden: expect.objectContaining({ antwoorden: [{ vraag_id: 'kanaal', waarde: 'Website' }] }),
      }),
    );
  });

  it('zegt het als er geen lead klaarstaat', () => {
    renderWithProviders(
      <ToastProvider>
        <StartCasusModal lead={null} kiesUit={[]} open onClose={vi.fn()} />
      </ToastProvider>,
    );
    expect(document.body.textContent).toContain('Er staat nu geen lead klaar');
    expect(startknop().hasAttribute('disabled')).toBe(true);
  });
});
