import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, waitFor } from '@testing-library/react';
import { useEffect } from 'react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import { TaskStatus } from '@/types';
import { OpNaamProvider, useOpNaam } from './OpNaamContext';

const updateTask = vi.fn();
vi.mock('@/api/tasks', async (orig) => ({
  ...(await orig<typeof import('@/api/tasks')>()),
  updateTask: (...args: unknown[]) => updateTask(...args),
}));
const getInitiatiefPersonen = vi.fn(async (_id: string) => [
  { id: 'p1', naam: 'Lid Een', is_agent: false },
  { id: 'ik', naam: 'Ik Zelf', is_agent: false },
]);
vi.mock('@/api/initiatieven', async (orig) => ({
  ...(await orig<typeof import('@/api/initiatieven')>()),
  getInitiatiefPersonen: (id: string) => getInitiatiefPersonen(id),
}));
// Wie er ingelogd is; 'buiten' is geen lid van het initiatief.
const ik = { id: 'ik' };
vi.mock('@/contexts/CurrentPersonContext', () => ({
  useCurrentPerson: () => ({ currentPerson: { id: ik.id, naam: 'Ik', is_agent: false }, people: [], setDevPersonId: () => {} }),
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

type Vraag = ReturnType<typeof useOpNaam>;
const handle: { vraag: Vraag | null } = { vraag: null };
function Grab() {
  const vraag = useOpNaam();
  useEffect(() => {
    handle.vraag = vraag;
  }, [vraag]);
  return null;
}

function render() {
  renderWithProviders(
    <ToastProvider>
      <OpNaamProvider>
        <Grab />
      </OpNaamProvider>
    </ToastProvider>,
  );
}

const zonder = { id: 't1', title: 'Wet lezen', assignee_id: null };
const knop = (tekst: string) => [...document.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === tekst);
const klik = async (tekst: string) => {
  await act(async () => {
    knop(tekst)!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
};
const vraag = async (...args: Parameters<Vraag>) => {
  await act(async () => handle.vraag!(...args));
};
/** De keuzelijst, zodra de namen binnen zijn. */
const lijst = () =>
  waitFor(() => {
    const s = [...document.querySelectorAll('select')].find((el) => [...el.options].some((o) => o.text === 'Lid Een'));
    expect(s).toBeTruthy();
    return s!;
  });

describe('OpNaamContext', () => {
  beforeEach(() => {
    updateTask.mockReset().mockResolvedValue({ id: 't1' });
    getInitiatiefPersonen.mockClear();
    ik.id = 'ik';
  });

  it('vraagt niets bij Te doen of als er al iemand op staat, en gaat meteen door', async () => {
    render();
    const daarna = vi.fn();
    await vraag(zonder, TaskStatus.OPEN, 'i1', daarna);
    await vraag({ ...zonder, assignee_id: 'p1' }, TaskStatus.IN_PROGRESS, 'i1', daarna);
    expect(knop('Op naam zetten')).toBeUndefined();
    expect(daarna).toHaveBeenCalledTimes(2);
  });

  it('in uitvoering: vraagt het, en Op mijn naam zet hem in één klik op jou', async () => {
    render();
    const daarna = vi.fn();
    await vraag(zonder, TaskStatus.IN_PROGRESS, 'i1', daarna);
    expect(document.body.textContent).toContain('staat nu in uitvoering, maar nog niet op naam');
    expect((await lijst()).value).toBe('');
    await waitFor(() => expect(knop('Op mijn naam')).toBeDefined());
    expect(updateTask).not.toHaveBeenCalled();
    expect(daarna).not.toHaveBeenCalled();

    await klik('Op mijn naam');
    expect(updateTask).toHaveBeenCalledWith('t1', { assignee_id: 'ik' });
    expect(daarna).toHaveBeenCalledOnce();
    expect(knop('Op mijn naam')).toBeUndefined();
  });

  it('afgerond: dezelfde vraag, en je kunt iemand anders kiezen', async () => {
    render();
    await vraag(zonder, TaskStatus.DONE, 'i1');
    expect(document.body.textContent).toContain('is afgerond, maar nog niet op naam');
    const select = await lijst();
    await act(async () => {
      select.value = 'p1';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await klik('Op naam zetten');
    expect(updateTask).toHaveBeenCalledWith('t1', { assignee_id: 'p1' });
  });

  it('Niet nu laat de taak zonder naam en gaat door', async () => {
    render();
    const daarna = vi.fn();
    await vraag(zonder, TaskStatus.IN_PROGRESS, 'i1', daarna);
    await klik('Niet nu');
    expect(updateTask).not.toHaveBeenCalled();
    expect(daarna).toHaveBeenCalledOnce();
    expect(knop('Op naam zetten')).toBeUndefined();
  });

  it('wie geen lid is, krijgt geen knop voor zichzelf; zonder keuze kan Op naam zetten niet', async () => {
    ik.id = 'buiten';
    render();
    await vraag(zonder, TaskStatus.IN_PROGRESS, 'i1');
    expect((await lijst()).value).toBe('');
    expect(knop('Op mijn naam')).toBeUndefined();
    expect(knop('Op naam zetten')!.hasAttribute('disabled')).toBe(true);
  });

  it('blijft open als opslaan mislukt', async () => {
    updateTask.mockRejectedValue(new Error('nee'));
    render();
    const daarna = vi.fn();
    await vraag(zonder, TaskStatus.IN_PROGRESS, 'i1', daarna);
    await waitFor(() => expect(knop('Op mijn naam')).toBeDefined());
    await klik('Op mijn naam');
    expect(daarna).not.toHaveBeenCalled();
    expect(knop('Op mijn naam')).toBeDefined();
  });

  it('zonder meegegeven initiatief: de leden van het initiatief van de casus', async () => {
    render();
    await vraag({ ...zonder, casus: { id: 'c1', title: 'Casus', initiatief_id: 'i2' } }, TaskStatus.IN_PROGRESS, null);
    await waitFor(() => expect(knop('Op mijn naam')).toBeDefined());
    expect(getInitiatiefPersonen).toHaveBeenCalledWith('i2');
    await klik('Op mijn naam');
    expect(updateTask).toHaveBeenCalledWith('t1', { assignee_id: 'ik' });
  });

  it('zonder meegegeven initiatief en zonder casus: de leden van het initiatief van de vraag', async () => {
    render();
    await vraag(
      { ...zonder, casus: null, issue: { id: 'v1', title: 'Vraag', casus_id: null, initiatief_id: 'i3' } },
      TaskStatus.IN_PROGRESS,
      null,
    );
    await waitFor(() => expect(knop('Op mijn naam')).toBeDefined());
    expect(getInitiatiefPersonen).toHaveBeenCalledWith('i3');
  });

  it('twee vragen kort na elkaar: de tweede wacht, en elke daarna draait op zijn beurt', async () => {
    render();
    const eerste = vi.fn();
    const tweede = vi.fn();
    await vraag(zonder, TaskStatus.DONE, 'i1', eerste);
    await vraag({ ...zonder, id: 't2', title: 'Brief schrijven' }, TaskStatus.IN_PROGRESS, 'i1', tweede);
    // Eén venster tegelijk, de eerste vraag eerst.
    expect(document.querySelectorAll('nldd-top-title-bar[text="Op naam zetten?"]')).toHaveLength(1);
    expect(document.body.textContent).toContain('"Wet lezen" is afgerond');

    await klik('Niet nu');
    expect(eerste).toHaveBeenCalledOnce();
    expect(tweede).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('"Brief schrijven" staat nu in uitvoering');

    await waitFor(() => expect(knop('Op mijn naam')).toBeDefined());
    await klik('Op mijn naam');
    expect(updateTask).toHaveBeenCalledWith('t2', { assignee_id: 'ik' });
    expect(tweede).toHaveBeenCalledOnce();
    expect(knop('Op naam zetten')).toBeUndefined();
  });

  it('twee keer sluiten draait daarna maar één keer', async () => {
    render();
    const daarna = vi.fn();
    await vraag(zonder, TaskStatus.IN_PROGRESS, 'i1', daarna);
    const nietNu = knop('Niet nu')!;
    await act(async () => {
      nietNu.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      nietNu.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(daarna).toHaveBeenCalledOnce();
  });

  it('de knop die je indrukt draait, de andere niet', async () => {
    let klaarMet: (v: unknown) => void = () => {};
    updateTask.mockImplementation(() => new Promise((r) => (klaarMet = r)));
    render();
    await vraag(zonder, TaskStatus.IN_PROGRESS, 'i1');
    const select = await lijst();
    await act(async () => {
      select.value = 'p1';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await waitFor(() => expect(knop('Op mijn naam')).toBeDefined());

    await klik('Op naam zetten');
    await waitFor(() => expect(knop('Op naam zetten')!.hasAttribute('loading')).toBe(true));
    expect(knop('Op mijn naam')!.hasAttribute('loading')).toBe(false);
    expect(knop('Op mijn naam')!.hasAttribute('disabled')).toBe(true);
    await act(async () => klaarMet({ id: 't1' }));
  });

  it('Op mijn naam draait zelf, Op naam zetten niet', async () => {
    let klaarMet: (v: unknown) => void = () => {};
    updateTask.mockImplementation(() => new Promise((r) => (klaarMet = r)));
    render();
    await vraag(zonder, TaskStatus.IN_PROGRESS, 'i1');
    await waitFor(() => expect(knop('Op mijn naam')).toBeDefined());

    await klik('Op mijn naam');
    await waitFor(() => expect(knop('Op mijn naam')!.hasAttribute('loading')).toBe(true));
    expect(knop('Op naam zetten')!.hasAttribute('loading')).toBe(false);
    await act(async () => klaarMet({ id: 't1' }));
  });
});
