import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import type { Casus } from '@/types';
import { KoelkastModal } from './KoelkastModal';

const zetInKoelkast = vi.fn();
vi.mock('@/api/casussen', async (orig) => ({
  ...(await orig<typeof import('@/api/casussen')>()),
  zetInKoelkast: (...args: unknown[]) => zetInKoelkast(...args),
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

const CASUS = { id: 'c1', lead_id: 'l1', title: 'Casus', fase: 'uitvoeren', startvoorwaarden: {}, team_count: 0, issue_count: 0, issue_done_count: 0, created_at: '2026-11-01T00:00:00Z' } as unknown as Casus;

const knop = (tekst: string) => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === tekst)!;
const klik = (tekst: string) => act(async () => { knop(tekst).dispatchEvent(new MouseEvent('click', { bubbles: true })); });
const typ = (sel: string, value: string) =>
  act(async () => { document.querySelector(sel)!.dispatchEvent(new CustomEvent('input', { detail: { value } })); });

function render(onClose = vi.fn()) {
  renderWithProviders(
    <ToastProvider>
      <KoelkastModal casus={CASUS} onClose={onClose} />
    </ToastProvider>,
  );
  return onClose;
}

describe('KoelkastModal', () => {
  beforeEach(() => zetInKoelkast.mockReset().mockResolvedValue({ ...CASUS }));

  it('slaat niets op zonder reden en datum', async () => {
    const onClose = render();
    await klik('In de koelkast zetten');
    expect(zetInKoelkast).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Zeg waarom de casus in de koelkast gaat.');
  });

  it('zet de casus in de koelkast met reden en datum', async () => {
    const onClose = render();
    await typ('nldd-multi-line-text-field', ' Partner heeft geen tijd ');
    await typ('nldd-date-field, nldd-text-field', '2099-01-15');
    await klik('In de koelkast zetten');
    expect(zetInKoelkast).toHaveBeenCalledWith('c1', { reden: 'Partner heeft geen tijd', verwacht_terug: '2099-01-15' });
    expect(onClose).toHaveBeenCalled();
  });
});
