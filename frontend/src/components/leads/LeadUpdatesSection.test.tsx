import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, waitFor } from '@testing-library/react';

import { clickNldd, renderWithProviders } from '@/test/utils';
import type { LeadUpdatePost } from '@/types';
import { LeadUpdatesSection } from './LeadUpdatesSection';

const listLeadUpdates = vi.fn();
const editLeadUpdate = vi.fn();
vi.mock('@/api/leadUpdates', async (orig) => ({
  ...(await orig<typeof import('@/api/leadUpdates')>()),
  listLeadUpdates: (...args: unknown[]) => listLeadUpdates(...args),
  editLeadUpdate: (...args: unknown[]) => editLeadUpdate(...args),
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const post = (id: string, extra: Partial<LeadUpdatePost>): LeadUpdatePost => ({
  id,
  lead_id: 'l1',
  titel: id,
  body_internal: null,
  body_public: null,
  mail_subject: null,
  mail_to: null,
  mail_cc: null,
  published_at: null,
  published_by_id: null,
  published_by_naam: null,
  created_at: '2026-11-20T00:00:00Z',
  updated_at: null,
  ...extra,
});

const POSTS = [
  post('Publiek', { body_public: 'Wat buiten mag', published_at: '2026-11-21T00:00:00Z' }),
  post('Concept met tekst', { body_public: 'Later' }),
  post('Concept zonder tekst', {}),
];

const rij = (titel: string) => document.querySelector(`nldd-text-cell[text="${titel}"]`)!.closest('nldd-list-item')!;
const segment = (titel: string, label: string) => rij(titel).querySelector(`nldd-list-item-segment[accessible-label="${label}"]`)!;
const knop = (tekst: string) => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === tekst)!;

async function render(publiekVast: boolean) {
  renderWithProviders(<LeadUpdatesSection leadId="l1" publiekVast={publiekVast} />);
  await waitFor(() => expect(document.querySelectorAll('nldd-text-cell')).toHaveLength(POSTS.length));
}

describe('LeadUpdatesSection bij een lead met casus', () => {
  beforeEach(() => {
    listLeadUpdates.mockReset().mockResolvedValue(POSTS);
    editLeadUpdate.mockReset().mockResolvedValue(POSTS[0]);
  });

  it('publiceert geen update met publieke tekst meer', async () => {
    await render(true);
    expect(segment('Concept met tekst', 'Publiceren').hasAttribute('disabled')).toBe(true);
    expect(segment('Concept zonder tekst', 'Publiceren').hasAttribute('disabled')).toBe(false);
    // Van de pagina halen kan wel.
    expect(segment('Publiek', 'Depubliceren').hasAttribute('disabled')).toBe(false);
  });

  it('laat titel en publieke tekst van een gepubliceerde update staan', async () => {
    await render(true);
    clickNldd(segment('Publiek', 'Bewerken'));
    await act(async () => {});
    expect(document.querySelector('nldd-text-field[accessible-label="Titel"]')!.hasAttribute('readonly')).toBe(true);
    expect(knop('Opslaan + publiceren').hasAttribute('disabled')).toBe(true);
    await act(async () => {
      clickNldd(knop('Opslaan als concept'));
    });
    const data = editLeadUpdate.mock.calls[0][2];
    expect(data).not.toHaveProperty('titel');
    expect(data).not.toHaveProperty('body_public');
  });

  it('zonder casus blijft alles open', async () => {
    await render(false);
    expect(segment('Concept met tekst', 'Publiceren').hasAttribute('disabled')).toBe(false);
    clickNldd(segment('Publiek', 'Bewerken'));
    await act(async () => {});
    expect(document.querySelector('nldd-text-field[accessible-label="Titel"]')!.hasAttribute('readonly')).toBe(false);
    await act(async () => {
      clickNldd(knop('Opslaan als concept'));
    });
    expect(editLeadUpdate.mock.calls[0][2]).toMatchObject({ titel: 'Publiek', body_public: 'Wat buiten mag' });
  });
});
