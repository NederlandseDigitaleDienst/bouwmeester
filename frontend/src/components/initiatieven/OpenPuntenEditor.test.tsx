import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, waitFor } from '@testing-library/react';

import { ApiError } from '@/api/client';
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
  // Met accolades: wat beforeEach teruggeeft, roept vitest na de test aan
  // als opruimfunctie, en mockResolvedValue geeft de mock zelf terug.
  beforeEach(() => {
    updateInitiatiefSettings.mockReset().mockResolvedValue({});
  });

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

  it('weigert de backend (422), dan blijft de lijst open met de reden eronder', async () => {
    updateInitiatiefSettings.mockRejectedValue(
      new ApiError(422, 'Unprocessable Entity', {
        detail: [{ loc: ['body', 'open_punten'], type: 'value_error', msg: 'Value error, Een open punt is maximaal 300 tekens' }],
      }),
    );
    const onKlaar = vi.fn();
    renderWithProviders(<OpenPuntenEditor initiatief={initiatief} onKlaar={onKlaar} />);
    const veld = document.querySelector('nldd-text-field[accessible-label="Punt 1"]')!;
    await act(async () => {
      veld.dispatchEvent(new CustomEvent('input', { detail: { value: 'Iets anders' } }));
    });
    await klik(knop('Opslaan'));

    await waitFor(() =>
      expect(document.querySelector('nldd-text[role="alert"]')?.textContent).toBe('Een open punt is maximaal 300 tekens.'),
    );
    expect(onKlaar).not.toHaveBeenCalled();
  });

  it('annuleren slaat niets op', async () => {
    const onKlaar = vi.fn();
    renderWithProviders(<OpenPuntenEditor initiatief={initiatief} onKlaar={onKlaar} />);
    await klik(knop('Annuleren'));
    expect(onKlaar).toHaveBeenCalled();
    expect(updateInitiatiefSettings).not.toHaveBeenCalled();
  });
});
