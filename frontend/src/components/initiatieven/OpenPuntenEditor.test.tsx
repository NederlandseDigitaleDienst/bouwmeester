import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/utils';
import type { InitiatiefDetail } from '@/types';
import { OpenPuntenEditor } from './OpenPuntenEditor';

const updateInitiatiefSettings = vi.fn();
vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  updateInitiatiefSettings: (...args: unknown[]) => updateInitiatiefSettings(...args),
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const initiatief = {
  id: 'i1',
  naam: 'Init',
  open_punten: ['De DoD samen vaststellen'],
} as unknown as InitiatiefDetail;

const knop = (tekst: string) => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === tekst)!;
const klik = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
};

describe('OpenPuntenEditor', () => {
  beforeEach(() => updateInitiatiefSettings.mockReset().mockResolvedValue({}));

  it('opslaan kan pas na een wijziging, en stuurt alleen de open punten', async () => {
    const onKlaar = vi.fn();
    renderWithProviders(<OpenPuntenEditor initiatief={initiatief} onKlaar={onKlaar} />);
    expect(knop('Opslaan').hasAttribute('disabled')).toBe(true);

    const veld = document.querySelector('nldd-text-field[accessible-label="Punt 1"]')!;
    await act(async () => {
      veld.dispatchEvent(new CustomEvent('input', { detail: { value: '  De DoD vaststellen  ' } }));
    });
    expect(knop('Opslaan').hasAttribute('disabled')).toBe(false);
    await klik(knop('Opslaan'));

    await waitFor(() => expect(updateInitiatiefSettings).toHaveBeenCalledTimes(1));
    expect(updateInitiatiefSettings.mock.calls[0]).toEqual(['i1', { open_punten: ['De DoD vaststellen'] }]);
    await waitFor(() => expect(onKlaar).toHaveBeenCalled());
  });

  it('annuleren slaat niets op', async () => {
    const onKlaar = vi.fn();
    renderWithProviders(<OpenPuntenEditor initiatief={initiatief} onKlaar={onKlaar} />);
    await klik(knop('Annuleren'));
    expect(onKlaar).toHaveBeenCalled();
    expect(updateInitiatiefSettings).not.toHaveBeenCalled();
  });
});
