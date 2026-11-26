import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { clickNldd, getByNlddLabel, renderWithProviders } from '@/test/utils';
import { IssueStatus, TaskPriority, TaskStatus, type BacklogIssue, type BacklogTask, type Task } from '@/types';
import { InitiatiefBacklog } from './InitiatiefBacklog';

/**
 * De bedrading rond het mini-kanban: na een sleepactie eerst de vraag of de
 * taak op naam moet, pas daarna de DoD; en een nieuwe taak in Afgerond die
 * alles af maakt, opent de DoD ook. De vraag en de DoD zelf zijn elders
 * getest (OpNaamContext.test, DodModal.test); hier staan ze als stub.
 */

const updateTask = vi.fn();
vi.mock('@/api/tasks', async (orig) => ({
  ...(await orig<typeof import('@/api/tasks')>()),
  updateTask: (...args: unknown[]) => updateTask(...args),
}));

const backlog: { issues: BacklogIssue[] } = { issues: [] };
vi.mock('@/hooks/useCasussen', async (orig) => ({
  ...(await orig<typeof import('@/hooks/useCasussen')>()),
  useBacklog: () => ({ data: { issues: backlog.issues, losse_taken: [] }, isLoading: false }),
}));
vi.mock('@/hooks/useInitiatieven', async (orig) => ({
  ...(await orig<typeof import('@/hooks/useInitiatieven')>()),
  useInitiatief: () => ({ data: undefined }),
}));

// De vraag naar een naam: hier alleen of en hoe hij wordt aangeroepen.
const vraagOpNaam = vi.fn();
vi.mock('@/contexts/OpNaamContext', async (orig) => ({
  ...(await orig<typeof import('@/contexts/OpNaamContext')>()),
  useOpNaam: () => vraagOpNaam,
}));

vi.mock('./DodModal', () => ({
  DodModal: ({ issue }: { issue: { title: string } | null }) => (issue ? <div>DoD bij {issue.title}</div> : null),
}));

// Taak toevoegen als stub: één knop die doet alsof de taak is aangemaakt.
vi.mock('./TaakAanmakenModal', () => ({
  TaakAanmakenModal: ({ open, status, onAangemaakt }: { open: boolean; status?: TaskStatus; onAangemaakt?: (t: Partial<Task>) => void }) =>
    open ? (
      <button type="button" onClick={() => onAangemaakt?.({ id: 'nieuw', title: 'Nieuw', status })}>
        stub aanmaken
      </button>
    ) : null,
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

function taak(id: string, status: TaskStatus, assignee_id: string | null = null): BacklogTask {
  return { id, title: `Taak ${id}`, status, priority: TaskPriority.NORMAAL, assignee_id, comment_count: 0, created_at: '2026-11-01T00:00:00Z' };
}

function vraagMet(tasks: BacklogTask[]): BacklogIssue {
  return {
    id: 'v1',
    casus_id: 'c1',
    casus: { id: 'c1', title: 'Casus', fase: 'verkennen', initiatief_id: 'i1' },
    title: 'Wie heeft recht?',
    status: IssueStatus.OPEN,
    is_onderzoeksvraag: true,
    sort_order: 0,
    dod_checked: [],
    tasks,
    created_at: '2026-11-01T00:00:00Z',
  };
}

async function renderBord(tasks: BacklogTask[]) {
  backlog.issues = [vraagMet(tasks)];
  renderWithProviders(
    <ToastProvider>
      <InitiatiefBacklog initiatiefId="i1" vasteCasusId="c1" />
    </ToastProvider>,
  );
  clickNldd(getByNlddLabel('Wie heeft recht?: uitklappen'));
  await waitFor(() => expect(document.querySelector('nldd-task-board')).not.toBeNull());
}

/** Wat het bord meldt bij slepen of Alt met de pijltjes. */
async function verplaats(id: string, naar: TaskStatus) {
  const bord = document.querySelector('nldd-task-board')!;
  const item = document.querySelector<HTMLElement>(`[data-taak-id="${id}"]`)!;
  await act(async () => {
    bord.dispatchEvent(new CustomEvent('nldd-move', { detail: { item, toColumn: naar } }));
  });
}

const dodOpen = () => screen.queryByText('DoD bij Wie heeft recht?') !== null;

describe('InitiatiefBacklog: op naam en DoD na een sleepactie', () => {
  beforeEach(() => {
    updateTask.mockReset().mockResolvedValue({ id: 't1' });
    vraagOpNaam.mockReset();
  });

  it('de laatste open taak naar Afgerond: eerst de vraag op naam, de DoD pas daarna', async () => {
    await renderBord([taak('t1', TaskStatus.OPEN), taak('t2', TaskStatus.DONE, 'p1')]);
    await verplaats('t1', TaskStatus.DONE);

    await waitFor(() => expect(vraagOpNaam).toHaveBeenCalledOnce());
    expect(updateTask).toHaveBeenCalledWith('t1', { status: TaskStatus.DONE });
    const [taakArg, status, initiatief, daarna] = vraagOpNaam.mock.calls[0];
    expect(taakArg).toMatchObject({ id: 't1', assignee_id: null });
    expect(status).toBe(TaskStatus.DONE);
    expect(initiatief).toBe('i1');
    // De DoD wacht op de vraag.
    expect(dodOpen()).toBe(false);

    await act(async () => daarna());
    expect(dodOpen()).toBe(true);
  });

  it('niet de laatste: wel de vraag, zonder DoD erna', async () => {
    await renderBord([taak('t1', TaskStatus.OPEN), taak('t2', TaskStatus.OPEN)]);
    await verplaats('t1', TaskStatus.IN_PROGRESS);

    await waitFor(() => expect(vraagOpNaam).toHaveBeenCalledOnce());
    const [, status, , daarna] = vraagOpNaam.mock.calls[0];
    expect(status).toBe(TaskStatus.IN_PROGRESS);
    expect(daarna).toBeUndefined();
    expect(dodOpen()).toBe(false);
  });

  it('mislukt opslaan: geen vraag en geen DoD', async () => {
    updateTask.mockRejectedValue(new Error('nee'));
    await renderBord([taak('t1', TaskStatus.OPEN)]);
    await verplaats('t1', TaskStatus.DONE);

    await waitFor(() => expect(updateTask).toHaveBeenCalled());
    await act(async () => {});
    expect(vraagOpNaam).not.toHaveBeenCalled();
    expect(dodOpen()).toBe(false);
  });
});

describe('InitiatiefBacklog: Taak toevoegen per kolom', () => {
  beforeEach(() => {
    vraagOpNaam.mockReset();
  });

  it('een nieuwe taak in Afgerond die alles af maakt, opent de DoD', async () => {
    await renderBord([taak('t1', TaskStatus.DONE, 'p1')]);
    clickNldd(getByNlddLabel('Taak toevoegen in Afgerond bij Wie heeft recht?'));
    await act(async () => screen.getByText('stub aanmaken').click());
    expect(dodOpen()).toBe(true);
  });

  it('een nieuwe taak in Afgerond terwijl er nog werk open is: geen DoD', async () => {
    await renderBord([taak('t1', TaskStatus.OPEN)]);
    clickNldd(getByNlddLabel('Taak toevoegen in Afgerond bij Wie heeft recht?'));
    await act(async () => screen.getByText('stub aanmaken').click());
    expect(dodOpen()).toBe(false);
  });

  it('een nieuwe taak in Te doen: geen DoD', async () => {
    await renderBord([taak('t1', TaskStatus.DONE, 'p1')]);
    clickNldd(getByNlddLabel('Taak toevoegen in Te doen bij Wie heeft recht?'));
    await act(async () => screen.getByText('stub aanmaken').click());
    expect(dodOpen()).toBe(false);
  });
});
