import { describe, it, expect, vi, beforeAll } from 'vitest';
import { fireEvent, waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { KlaarOmTeDelen } from '@/components/initiatieven/KlaarOmTeDelen';
import { renderWithProviders } from '@/test/utils';
import { IssueStatus, type InitiatiefDetail, type KlaarCasus, type KlaarVraag } from '@/types';
import { CasusNaarBuiten } from './CasusNaarBuiten';
import { NaarBuiten } from './NaarBuiten';
import { OnderzoeksverslagBlok } from './OnderzoeksverslagBlok';

const klaar = vi.fn();
vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  getKlaarOmTeDelen: (...args: unknown[]) => klaar(...args),
}));
vi.mock('@/api/issues', async (orig) => ({
  ...(await orig<typeof import('@/api/issues')>()),
  getVerslag: async () => ({
    id: 'v1',
    bestandsnaam: 'Concept v3 Jansen.pdf',
    content_type: 'application/pdf',
    bestandsgrootte: 1234,
    uploaded_by_naam: null,
    created_at: '2026-11-20T10:00:00Z',
    updated_at: null,
    openbaar_op: null,
    openbaar_door_naam: null,
  }),
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const VRAAG = {
  id: 'is1',
  casus_id: 'c1',
  initiatief_id: 'i1',
  is_onderzoeksvraag: true,
  status: IssueStatus.DONE,
  public_title: 'Kan het?',
  public_answer: 'Ja.',
  published_at: '2026-11-20T10:00:00Z',
};

const CASUS: KlaarCasus = {
  id: 'c1',
  titel: 'Casus binnen',
  lessen: 'Intern geleerd',
  public_title: 'Casus buiten',
  public_resultaat: 'Resultaat',
  public_lessen: null,
  published_at: '2026-11-20T10:00:00Z',
  in_gepubliceerde_update: false,
  afgerond_op: null,
};

const knoppen = () => [...document.querySelectorAll('nldd-button')].map((b) => b.getAttribute('text'));
const labels = () => [...document.querySelectorAll('nldd-tag')].map((t) => t.getAttribute('text'));

function render(ui: React.ReactElement) {
  return renderWithProviders(<ToastProvider>{ui}</ToastProvider>);
}

describe('NaarBuiten', () => {
  it('geeft wie mag vrijgeven de knoppen', () => {
    render(<NaarBuiten issue={VRAAG} kanVrijgeven />);
    expect(knoppen()).toContain('Intrekken');
  });

  it('toont wie niet mag vrijgeven wat buiten staat, zonder knoppen', () => {
    render(<NaarBuiten issue={VRAAG} kanVrijgeven={false} />);
    expect(knoppen()).toEqual([]);
    expect(document.body.textContent).toContain('Kan het?');
    expect(document.body.textContent).toContain('kan een bijdrager of eigenaar');
    expect(document.querySelector('nldd-text-field, nldd-text-editor')).toBeNull();
  });

  it('belooft geen roadmap', () => {
    render(<NaarBuiten issue={{ ...VRAAG, status: IssueStatus.OPEN }} kanVrijgeven />);
    render(<NaarBuiten issue={VRAAG} kanVrijgeven />);
    expect(document.body.textContent).not.toMatch(/roadmap/i);
  });
});

describe('CasusNaarBuiten', () => {
  it('geeft wie mag vrijgeven velden en knoppen', () => {
    render(<CasusNaarBuiten casus={CASUS} kanWijzigen />);
    expect(knoppen()).toContain('Intrekken');
  });

  it('toont wie niet mag vrijgeven alleen de tekst', () => {
    render(<CasusNaarBuiten casus={CASUS} kanWijzigen={false} />);
    expect(knoppen()).toEqual([]);
    expect(document.body.textContent).toContain('Casus buiten');
    expect(document.querySelector('nldd-text-field, nldd-text-editor')).toBeNull();
  });
});

describe('OnderzoeksverslagBlok', () => {
  it('openbaar maken alleen voor wie mag vrijgeven', async () => {
    render(<OnderzoeksverslagBlok issue={VRAAG} kanVrijgeven={false} />);
    await waitFor(() => expect(knoppen()).toContain('Vervangen'));
    expect(knoppen()).not.toContain('Openbaar maken');
  });

  it('noemt het bestand in het akkoordvenster', async () => {
    render(<OnderzoeksverslagBlok issue={VRAAG} kanVrijgeven />);
    await waitFor(() => expect(knoppen()).toContain('Openbaar maken'));
    expect(document.body.textContent).toContain('Het verslag "Concept v3 Jansen.pdf" verschijnt op de publieke pagina');
  });
});

describe('KlaarOmTeDelen', () => {
  const vraag = (extra: Partial<KlaarVraag>): KlaarVraag => ({
    id: 'is1',
    casus_id: 'c1',
    casus_titel: 'Casus binnen',
    titel: 'Vraag binnen',
    public_title: 'Kan het?',
    public_answer: 'Ja.',
    published_at: null,
    in_gepubliceerde_update: false,
    verslag_openbaar: false,
    ...extra,
  });
  const initiatief = { id: 'i1' } as InitiatiefDetail;

  it('"In een update" alleen zolang de vraag buiten is', async () => {
    // Ingetrokken: niet meer buiten, ook al hing hij aan een gepubliceerde update.
    klaar.mockResolvedValue({ vragen: [vraag({ in_gepubliceerde_update: true })], casussen: [] });
    render(<KlaarOmTeDelen initiatief={initiatief} canEdit />);
    await waitFor(() => expect(document.body.textContent).toContain('Vraag binnen'));
    expect(labels()).not.toContain('In een update');
    expect(labels()).toContain('Binnen');
  });

  it('toont "In een update" voor een vraag die buiten is', async () => {
    klaar.mockResolvedValue({
      vragen: [vraag({ published_at: '2026-11-20T10:00:00Z', in_gepubliceerde_update: true })],
      casussen: [],
    });
    render(<KlaarOmTeDelen initiatief={initiatief} canEdit />);
    await waitFor(() => expect(labels()).toContain('In een update'));
  });

  it('noemt geen RegelReis', async () => {
    klaar.mockResolvedValue({ vragen: [], casussen: [] });
    render(<KlaarOmTeDelen initiatief={initiatief} canEdit />);
    await waitFor(() => expect(document.body.textContent).toContain('nog geen afgeronde casussen'));
    // Het blok met de casussen openklappen.
    const blokken = [...document.querySelectorAll('section h3 button')];
    fireEvent.click(blokken[1]);
    expect(document.body.textContent).toContain('Nog geen afgeronde casussen');
    expect(document.body.textContent).toContain('casusfunnel');
    expect(document.body.textContent).not.toContain('RegelReis');
  });
});
