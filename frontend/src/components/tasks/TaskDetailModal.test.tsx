import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { act, waitFor } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import { TaskPriority, TaskStatus, type Task } from '@/types';
import { TaskDetailModal } from './TaskDetailModal';

/**
 * De status in het taakdetail is de weg zonder slepen. Ook daar volgt na
 * opslaan de vraag of de taak op naam moet (zie OpNaamContext.test).
 */

const taak: Task = {
  id: 't1',
  title: 'Wet lezen',
  status: TaskStatus.OPEN,
  priority: TaskPriority.NORMAAL,
  casus_id: 'c1',
  casus: { id: 'c1', title: 'Casus', fase: 'verkennen', initiatief_id: 'i1' },
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
};

const updateTask = vi.fn();
vi.mock('@/api/tasks', async (orig) => ({
  ...(await orig<typeof import('@/api/tasks')>()),
  getTask: async () => taak,
  getWorkTypes: async () => [],
  updateTask: (...args: unknown[]) => updateTask(...args),
}));
vi.mock('@/hooks/useIssues', async (orig) => ({
  ...(await orig<typeof import('@/hooks/useIssues')>()),
  useIssues: () => ({ data: [] }),
}));
vi.mock('@/hooks/useInitiatiefPersonOptions', async (orig) => ({
  ...(await orig<typeof import('@/hooks/useInitiatiefPersonOptions')>()),
  useInitiatiefPersonOptions: () => [{ value: '', label: 'Niemand' }],
}));
vi.mock('@/hooks/useTaskFormOptions', () => ({
  useTaskFormOptions: () => ({ nodeOptions: [], eenheidOptions: [], personOptions: [] }),
}));

// Opmerkingen en bijlagen doen hier niet mee.
vi.mock('./TaskCommentsSection', () => ({ TaskCommentsSection: () => null }));
vi.mock('./TaskAttachmentsSection', () => ({ TaskAttachmentsSection: () => null }));
vi.mock('@/contexts/NodeDetailContext', () => ({ useNodeDetail: () => ({ openNodeDetail: vi.fn() }) }));
vi.mock('@/contexts/OpdrachtDetailContext', () => ({ useOpdrachtDetail: () => ({ openOpdrachtDetail: vi.fn() }) }));

const vraagOpNaam = vi.fn();
vi.mock('@/contexts/OpNaamContext', async (orig) => ({
  ...(await orig<typeof import('@/contexts/OpNaamContext')>()),
  useOpNaam: () => vraagOpNaam,
}));

beforeAll(() => {
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
});

/** De keuzelijst Status, zodra de taak geladen is. */
const statusLijst = () =>
  waitFor(() => {
    const s = [...document.querySelectorAll('select')].find((el) => [...el.options].some((o) => o.text === 'In uitvoering'));
    expect(s).toBeTruthy();
    return s!;
  });

describe('TaskDetailModal: status wijzigen vraagt of de taak op naam moet', () => {
  beforeEach(() => {
    updateTask.mockReset().mockResolvedValue({ ...taak, status: TaskStatus.IN_PROGRESS });
    vraagOpNaam.mockReset();
  });

  it('na opslaan, met de taak, de nieuwe status en het initiatief van de casus', async () => {
    renderWithProviders(
      <ToastProvider>
        <TaskDetailModal taskId="t1" open onClose={vi.fn()} />
      </ToastProvider>,
    );
    const select = await statusLijst();
    await act(async () => {
      select.value = TaskStatus.IN_PROGRESS;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await waitFor(() => expect(vraagOpNaam).toHaveBeenCalledOnce());
    expect(updateTask).toHaveBeenCalledWith('t1', { status: TaskStatus.IN_PROGRESS });
    expect(vraagOpNaam).toHaveBeenCalledWith(expect.objectContaining({ id: 't1', status: TaskStatus.OPEN }), TaskStatus.IN_PROGRESS, 'i1');
  });
});
