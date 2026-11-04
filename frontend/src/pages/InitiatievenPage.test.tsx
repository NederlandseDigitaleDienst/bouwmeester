import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import { Route, Routes, useParams } from 'react-router-dom';

import { renderWithProviders } from '@/test/utils';
import { InitiatievenPage } from './InitiatievenPage';

/**
 * Wie in een initiatief zit, komt er via de pagina Initiatieven: het kaartje
 * staat er, en een klik opent het initiatief. De backend-kant (wie wat ziet)
 * bewaakt tests/test_initiatief_toegang.py.
 */

const getInitiatieven = vi.fn();
vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  getInitiatieven: (...args: unknown[]) => getInitiatieven(...args),
}));
// Bestanden neerzetten op de pagina speelt hier geen rol.
vi.mock('@/hooks/useGlobalFileDropContext', () => ({
  useGlobalFileDropContext: () => ({ subscribe: () => () => {} }),
}));
vi.mock('@/components/leads/LeadIntakeDialog', () => ({ LeadIntakeDialog: () => null }));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const REGELRECHT = {
  id: 'i-rr',
  naam: 'Regelrecht',
  slug: 'regelrecht',
  beschrijving: 'Wetgeving als uitvoerbare code.',
  kleur: null,
  funnel_enabled: true,
  public_page_enabled: true,
  lead_count: 17,
  active_lead_count: 3,
  member_count: 5,
  last_published_at: null,
};

function Detail() {
  const { id } = useParams();
  return <div>Initiatief {id} geopend</div>;
}

function renderPagina() {
  renderWithProviders(
    <Routes>
      <Route path="/" element={<InitiatievenPage />} />
      <Route path="/initiatieven/:id" element={<Detail />} />
    </Routes>,
  );
}

describe('InitiatievenPage', () => {
  beforeEach(() => getInitiatieven.mockReset());

  it('toont het initiatief waar je in zit, en een klik opent het', async () => {
    getInitiatieven.mockResolvedValue([REGELRECHT]);
    renderPagina();
    await waitFor(() => expect(document.querySelector('nldd-card[accessible-label="Regelrecht"]')).toBeTruthy());
    expect(document.body.textContent).not.toContain('Je bent nog bij geen enkel initiatief betrokken');
    const kaart = document.querySelector('nldd-card[accessible-label="Regelrecht"]')!;
    expect(kaart.getAttribute('href')).toBe('/initiatieven/i-rr');
    await act(async () => {
      kaart.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    });
    expect(screen.getByText('Initiatief i-rr geopend')).toBeTruthy();
  });

  it('de melding "geen enkel initiatief" alleen als er echt geen is', async () => {
    getInitiatieven.mockResolvedValue([]);
    renderPagina();
    await waitFor(() => expect(document.body.textContent).toContain('Je bent nog bij geen enkel initiatief betrokken'));
  });
});
