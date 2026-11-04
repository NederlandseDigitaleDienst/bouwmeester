import { describe, it, expect, vi, beforeAll } from 'vitest';
import { waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import type { CasusDetail } from '@/types';
import { CasusTeamModal } from './CasusTeamModal';

vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  // Leden van het initiatief: een contact van de lead en een collega.
  getInitiatiefPersonen: async () => [
    { id: 'p-lid-contact', naam: 'Contact en lid', functie: 'Jurist', rol: 'contributor', via_eenheden: [] },
    { id: 'p-collega', naam: 'Collega', functie: null, rol: 'contributor', via_eenheden: [] },
  ],
}));
vi.mock('@/api/leads', async (orig) => ({
  ...(await orig<typeof import('@/api/leads')>()),
  getLead: async () => ({
    id: 'l1',
    contacts: [
      { id: 'c1', person_id: 'p-lid-contact', person_naam: 'Contact en lid', rol: 'teamlid', created_at: '' },
      { id: 'c2', person_id: 'p-extern', person_naam: 'Extern contact', rol: 'opdrachtgever', created_at: '' },
      // Dezelfde persoon met een tweede rol: één keer noemen.
      { id: 'c3', person_id: 'p-extern', person_naam: 'Extern contact', rol: 'betrokken', created_at: '' },
    ],
  }),
}));
vi.mock('@/api/people', async (orig) => ({
  ...(await orig<typeof import('@/api/people')>()),
  getPeople: async () => [],
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const CASUS = {
  id: 'c1',
  lead_id: 'l1',
  initiatief_id: 'i1',
  initiatief: { id: 'i1', naam: 'Regelrecht' },
  team: [],
} as unknown as CasusDetail;

describe('CasusTeamModal', () => {
  it('noemt contacten van de lead die eerst lid moeten worden', async () => {
    renderWithProviders(
      <ToastProvider>
        <CasusTeamModal casus={CASUS} onClose={vi.fn()} />
      </ToastProvider>,
    );
    await waitFor(() => expect(document.body.textContent).toContain('Contact op de lead, nog geen lid: Extern contact.'));
    // Een contact dat al lid is, staat niet in die melding: die is gewoon te kiezen.
    expect(document.body.textContent).not.toContain('nog geen lid: Contact en lid');
    expect(document.body.textContent?.match(/Extern contact/g)).toHaveLength(1);
  });
});
