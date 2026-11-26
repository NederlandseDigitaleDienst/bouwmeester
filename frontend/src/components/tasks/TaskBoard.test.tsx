import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { clickNldd, getByNlddLabel, renderWithProviders } from '@/test/utils';
import { TaskPriority, TaskStatus, type Task } from '@/types';
import { TaskBoard } from './TaskBoard';
import { TaskCard } from './TaskCard';

/**
 * De bedrading naar de vraag "Op naam zetten?" vanuit het takenbord buiten
 * een casus en het afvinkrondje op een kaartje. De vraag zelf staat in
 * OpNaamContext.test; hier alleen of hij na opslaan met de goede taak,
 * status en het initiatief van de casus wordt aangeroepen.
 */

const updateTask = vi.fn();
vi.mock('@/api/tasks', async (orig) => ({
  ...(await orig<typeof import('@/api/tasks')>()),
  updateTask: (...args: unknown[]) => updateTask(...args),
}));

const vraagOpNaam = vi.fn();
vi.mock('@/contexts/OpNaamContext', async (orig) => ({
  ...(await orig<typeof import('@/contexts/OpNaamContext')>()),
  useOpNaam: () => vraagOpNaam,
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

function taak(overrides: Partial<Task> = {}): Task {
  return {
    id: 't1',
    title: 'Wet lezen',
    status: TaskStatus.OPEN,
    priority: TaskPriority.NORMAAL,
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    ...overrides,
  };
}

const metCasus = { casus: { id: 'c1', title: 'Casus', fase: 'verkennen', initiatief_id: 'i1' } };

/** Laat een kaartje vallen in de kolom met dit label, zoals slepen dat doet. */
function laatVallen(taskId: string, kolom: string) {
  const doel = screen.getByText(kolom).closest('.task-board-column')!;
  fireEvent.drop(doel, { dataTransfer: { getData: () => taskId } });
}

describe('TaskBoard: slepen vraagt of de taak op naam moet', () => {
  beforeEach(() => {
    updateTask.mockReset().mockResolvedValue({ id: 't1' });
    vraagOpNaam.mockReset();
  });

  it('na opslaan, met de taak zoals hij was, de nieuwe status en het initiatief van de casus', async () => {
    const t = taak(metCasus);
    renderWithProviders(
      <ToastProvider>
        <TaskBoard tasks={[t]} onEditTask={vi.fn()} />
      </ToastProvider>,
    );
    laatVallen('t1', 'In uitvoering');
    await waitFor(() => expect(vraagOpNaam).toHaveBeenCalledOnce());
    expect(updateTask).toHaveBeenCalledWith('t1', { status: TaskStatus.IN_PROGRESS });
    expect(vraagOpNaam).toHaveBeenCalledWith(t, TaskStatus.IN_PROGRESS, 'i1');
  });

  it('buiten een casus: zonder initiatief, dan is iedereen te kiezen', async () => {
    const t = taak();
    renderWithProviders(
      <ToastProvider>
        <TaskBoard tasks={[t]} onEditTask={vi.fn()} />
      </ToastProvider>,
    );
    laatVallen('t1', 'Afgerond');
    await waitFor(() => expect(vraagOpNaam).toHaveBeenCalledWith(t, TaskStatus.DONE, undefined));
  });

  it('mislukt opslaan of dezelfde kolom: geen vraag', async () => {
    updateTask.mockRejectedValue(new Error('nee'));
    renderWithProviders(
      <ToastProvider>
        <TaskBoard tasks={[taak()]} onEditTask={vi.fn()} />
      </ToastProvider>,
    );
    laatVallen('t1', 'Open');
    laatVallen('t1', 'Afgerond');
    await waitFor(() => expect(updateTask).toHaveBeenCalledOnce());
    await act(async () => {});
    expect(vraagOpNaam).not.toHaveBeenCalled();
  });
});

describe('TaskCard: afvinken vraagt of de taak op naam moet', () => {
  beforeEach(() => {
    updateTask.mockReset().mockResolvedValue({ id: 't1' });
    vraagOpNaam.mockReset();
  });

  it('afvinken: de vraag na opslaan, met Afgerond', async () => {
    const t = taak(metCasus);
    renderWithProviders(
      <ToastProvider>
        <TaskCard task={t} />
      </ToastProvider>,
    );
    clickNldd(getByNlddLabel('Markeer als afgerond'));
    await waitFor(() => expect(vraagOpNaam).toHaveBeenCalledWith(t, TaskStatus.DONE, 'i1'));
    expect(updateTask).toHaveBeenCalledWith('t1', { status: TaskStatus.DONE });
  });

  it('terugzetten naar Te doen geeft de vraag Te doen mee, en die vraagt niets', async () => {
    const t = taak({ status: TaskStatus.DONE });
    renderWithProviders(
      <ToastProvider>
        <TaskCard task={t} />
      </ToastProvider>,
    );
    clickNldd(getByNlddLabel('Markeer als niet afgerond'));
    await waitFor(() => expect(vraagOpNaam).toHaveBeenCalledWith(t, TaskStatus.OPEN, undefined));
  });
});
