import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { InitiatiefIdContext } from '@/hooks/useInitiatiefPersonOptions';
import { renderWithProviders } from '@/test/utils';
import { TaskStatus } from '@/types';
import { TaakAanmakenModal } from './TaakAanmakenModal';

const createTask = vi.fn();
vi.mock('@/api/tasks', async (orig) => ({
  ...(await orig<typeof import('@/api/tasks')>()),
  createTask: (...args: unknown[]) => createTask(...args),
}));
vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  getInitiatiefPersonen: async () => [
    { id: 'p1', naam: 'Lid Een', is_agent: false },
    { id: 'ik', naam: 'Ik Zelf', is_agent: false },
  ],
}));
// Wie er ingelogd is; 'buiten' is geen lid van het initiatief.
const ik = { id: 'ik' };
vi.mock('@/contexts/CurrentPersonContext', () => ({
  useCurrentPerson: () => ({ currentPerson: { id: ik.id, naam: 'Ik Zelf', is_agent: false }, people: [], setDevPersonId: () => {} }),
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

function renderModal(onClose = vi.fn(), status?: TaskStatus, onAangemaakt = vi.fn()) {
  renderWithProviders(
    <ToastProvider>
      <InitiatiefIdContext.Provider value="i1">
        <TaakAanmakenModal open onClose={onClose} issue={{ id: 'v1', title: 'Wie heeft recht?' }} status={status} onAangemaakt={onAangemaakt} />
      </InitiatiefIdContext.Provider>
    </ToastProvider>,
  );
  return onClose;
}

const typTitel = async (tekst: string) => {
  const veld = document.querySelector('nldd-text-field')!;
  await act(async () => {
    veld.dispatchEvent(new CustomEvent('input', { detail: { value: tekst } }));
  });
};

const knop = (tekst: string) => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === tekst)!;

const toevoegen = async () => {
  await act(async () => {
    knop('Toevoegen').dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
};

/** De keuzelijst Op naam van, zodra de leden binnen zijn. */
const eigenaarLijst = () =>
  waitFor(() => {
    const s = [...document.querySelectorAll('select')].find((el) => [...el.options].some((o) => o.text === 'Lid Een'));
    expect(s).toBeTruthy();
    return s!;
  });

describe('TaakAanmakenModal', () => {
  beforeEach(() => {
    createTask.mockReset().mockResolvedValue({ id: 'nieuw', status: 'open' });
    ik.id = 'ik';
  });

  it('het titelveld krijgt de focus als het venster opengaat', () => {
    renderModal();
    // Het venster zoekt bij openen naar [autofocus]; zonder krijgt het zelf de focus.
    expect(document.querySelector('nldd-text-field')!.hasAttribute('autofocus')).toBe(true);
  });

  it('Toevoegen kan pas met een titel', async () => {
    renderModal();
    expect(knop('Toevoegen').hasAttribute('disabled')).toBe(true);
    await typTitel('Wet lezen');
    expect(knop('Toevoegen').hasAttribute('disabled')).toBe(false);
  });

  it('maakt de taak in Te doen onder de vraag, zonder eigenaar', async () => {
    const onClose = renderModal();
    await typTitel('  Wet lezen  ');
    await toevoegen();
    expect(createTask).toHaveBeenCalledWith({ title: 'Wet lezen', issue_id: 'v1' });
    expect(onClose).toHaveBeenCalled();
  });

  it('geeft de gekozen eigenaar meteen mee, uit de leden van het initiatief', async () => {
    renderModal(vi.fn(), TaskStatus.IN_PROGRESS);
    const select = await eigenaarLijst();
    await act(async () => {
      select.value = 'p1';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await typTitel('Wet lezen');
    await toevoegen();
    expect(createTask).toHaveBeenCalledWith({ title: 'Wet lezen', issue_id: 'v1', status: TaskStatus.IN_PROGRESS, assignee_id: 'p1' });
  });

  it('blijft open als opslaan mislukt', async () => {
    createTask.mockRejectedValue(new Error('nee'));
    const onClose = renderModal();
    await typTitel('Wet lezen');
    await toevoegen();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('in Te doen vraagt het venster niet naar een eigenaar, ook niet als je lid bent', async () => {
    renderModal();
    // Wacht tot de leden binnen zouden zijn; er komt toch geen keuzelijst.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(document.querySelector('nldd-form-field[label="Op naam van"]')).toBeNull();
    expect([...document.querySelectorAll('select')].some((el) => [...el.options].some((o) => o.text === 'Lid Een'))).toBe(false);
  });

  it.each([TaskStatus.IN_PROGRESS, TaskStatus.DONE])('in %s krijgt de taak die status, met jou alvast als eigenaar', async (status) => {
    const onAangemaakt = vi.fn();
    createTask.mockResolvedValue({ id: 'nieuw', status });
    renderModal(vi.fn(), status, onAangemaakt);
    await waitFor(async () => expect((await eigenaarLijst()).value).toBe('ik'));
    // Hetzelfde woord als in de vraag Op naam zetten?.
    expect(document.querySelector('nldd-form-field[label="Op naam van"]')).not.toBeNull();
    await typTitel('Wet lezen');
    await toevoegen();
    expect(createTask).toHaveBeenCalledWith({ title: 'Wet lezen', issue_id: 'v1', status, assignee_id: 'ik' });
    expect(onAangemaakt).toHaveBeenCalledWith({ id: 'nieuw', status });
  });

  it('Niemand kiezen blijft Niemand, ook in In uitvoering', async () => {
    renderModal(vi.fn(), TaskStatus.IN_PROGRESS);
    const select = await eigenaarLijst();
    await waitFor(() => expect(select.value).toBe('ik'));
    await act(async () => {
      select.value = '';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await typTitel('Wet lezen');
    await toevoegen();
    expect(createTask).toHaveBeenCalledWith({ title: 'Wet lezen', issue_id: 'v1', status: TaskStatus.IN_PROGRESS });
  });

  it('wie geen lid is, staat er niet alvast op', async () => {
    ik.id = 'buiten';
    renderModal(vi.fn(), TaskStatus.IN_PROGRESS);
    expect((await eigenaarLijst()).value).toBe('');
  });
});
