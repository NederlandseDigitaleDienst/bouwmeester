import { useState, useMemo, useCallback } from 'react';
import { ViewToggle } from '@/components/common/ViewToggle';
import type { ViewToggleOption } from '@/components/common/ViewToggle';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { TaskList } from './TaskList';
import { TaskBoard } from './TaskBoard';
import { TaskPersonalView } from './TaskPersonalView';
import { TaskCreateForm } from './TaskCreateForm';
import { usePeople } from '@/hooks/usePeople';
import { useOrganisatieFlat } from '@/hooks/useOrganisatie';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import {
  TaskStatus,
  TaskPriority,
  TASK_STATUS_LABELS,
  TASK_PRIORITY_LABELS,
  formatOrganisatieType,
  formatFunctie,
} from '@/types';
import type { Task } from '@/types';
import type { SelectOption } from '@/components/common/CreatableSelect';
import { NlddButton } from '@/components/nldd/NlddButton';

type ViewMode = 'list' | 'board' | 'personal';

const VIEW_OPTIONS: ViewToggleOption<ViewMode>[] = [
  { value: 'list', label: 'Lijst', icon: 'list' },
  { value: 'board', label: 'Bord', icon: 'columns-3' },
  { value: 'personal', label: 'Persoonlijk', icon: 'person' },
];

const VIEW_STORAGE_KEY = 'tasks-view-mode';
const MY_TASKS_SENTINEL = '__me__';

function getStoredView(): ViewMode {
  try {
    const stored = localStorage.getItem(VIEW_STORAGE_KEY);
    if (stored === 'board' || stored === 'personal') return stored;
  } catch {
    // localStorage unavailable (e.g. private browsing).
  }
  return 'list';
}

const statusOptions: SelectOption[] = [
  { value: '', label: 'Alle statussen' },
  ...Object.values(TaskStatus).map((s) => ({
    value: s,
    label: TASK_STATUS_LABELS[s],
  })),
];

const priorityOptions: SelectOption[] = [
  { value: '', label: 'Alle prioriteiten' },
  ...Object.values(TaskPriority).map((p) => ({
    value: p,
    label: TASK_PRIORITY_LABELS[p],
  })),
];

interface TaskViewProps {
  tasks: Task[];
  /** Pre-set node_id when creating a new task from within a node */
  defaultNodeId?: string;
}

export function TaskView({ tasks, defaultNodeId }: TaskViewProps) {
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>(getStoredView);
  const { openTaskDetail } = useTaskDetail();
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [priorityFilter, setPriorityFilter] = useState<string>('');
  const [personFilter, setPersonFilter] = useState<string>('');
  const [eenheidFilter, setEenheidFilter] = useState<string>('');

  const { data: people } = usePeople();
  const { data: eenheden } = useOrganisatieFlat();
  const { currentPerson } = useCurrentPerson();

  const personOptions: SelectOption[] = useMemo(() => [
    { value: '', label: 'Alle personen' },
    ...(currentPerson
      ? [{
          value: MY_TASKS_SENTINEL,
          label: `Mijn taken (${currentPerson.naam})`,
        }]
      : []),
    ...(people ?? []).map((p) => ({
      value: p.id,
      label: p.naam,
      description: formatFunctie(p.functie),
    })),
  ], [people, currentPerson]);

  const eenheidOptions: SelectOption[] = useMemo(() => [
    { value: '', label: 'Alle eenheden' },
    ...(eenheden ?? []).map((e) => ({
      value: e.id,
      label: e.naam,
      description: formatOrganisatieType(e.type),
    })),
  ], [eenheden]);

  const handleViewChange = (mode: ViewMode) => {
    setViewMode(mode);
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, mode);
    } catch {
      // localStorage unavailable (e.g. private browsing).
    }
  };

  const handleTaskClick = useCallback((task: Task) => {
    openTaskDetail(task.id);
  }, [openTaskDetail]);

  const filteredTasks = useMemo(() => {
    const effectivePersonId = personFilter === MY_TASKS_SENTINEL
      ? currentPerson?.id ?? null
      : personFilter || null;
    return tasks.filter((task) => {
      if (statusFilter && task.status !== statusFilter) return false;
      if (priorityFilter && task.priority !== priorityFilter) return false;
      if (effectivePersonId && task.assignee_id !== effectivePersonId) return false;
      if (eenheidFilter && task.organisatie_eenheid_id !== eenheidFilter) return false;
      return true;
    });
  }, [tasks, statusFilter, priorityFilter, personFilter, eenheidFilter, currentPerson]);

  return (
    <nldd-container gap="24">
      {/* Filters on the left, the view switcher and the new-task action on
          the right, in one row. nldd-toolbar owns the start/end split, so
          "push this to the right" is a slot rather than a spacer, and it moves
          items into an overflow menu when the row runs out of room. Same
          structure as CorpusPage. */}
      <nldd-toolbar accessible-label="Taakacties">
        <nldd-toolbar-item slot="start" priority={1} min-width="60%">
          {/* Filters share the toolbar row with the actions, and wrap only
              when the room runs out. `min-width` makes the item fluid; a
              percentage lets it give way to the end items instead of pushing
              them into the overflow menu. Each field has a fixed width,
              because a fit-content container measures its children and they
              measure it back. */}
          <nldd-container layout="wrap" gap="8" vertical-alignment="center">
            <nldd-container width="176px">
              <CreatableSelect
                value={statusFilter}
                onChange={setStatusFilter}
                options={statusOptions}
                placeholder="Alle statussen"
                searchable={false}
              />
            </nldd-container>

            <nldd-container width="176px">
              <CreatableSelect
                value={priorityFilter}
                onChange={setPriorityFilter}
                options={priorityOptions}
                placeholder="Alle prioriteiten"
                searchable={false}
              />
            </nldd-container>

            <nldd-container width="208px">
              <CreatableSelect
                value={personFilter}
                onChange={setPersonFilter}
                options={personOptions}
                placeholder="Alle personen"
              />
            </nldd-container>

            <nldd-container width="208px">
              <CreatableSelect
                value={eenheidFilter}
                onChange={setEenheidFilter}
                options={eenheidOptions}
                placeholder="Alle eenheden"
              />
            </nldd-container>
          </nldd-container>
        </nldd-toolbar-item>
        <nldd-toolbar-item slot="end" priority={3}>
          {/* A view switcher, not a single action, so it gets the highest
              priority: a lower number overflows FIRST, and a switcher that
              disappears into a menu leaves no way to tell which view you are
              looking at. Matches CorpusPage. */}
          <ViewToggle value={viewMode} onChange={handleViewChange} options={VIEW_OPTIONS} />
        </nldd-toolbar-item>
        <nldd-toolbar-item slot="end" priority={2}>
          <NlddButton startIcon="plus" onClick={() => setShowCreateForm(true)} text="Nieuwe taak" compactBelowSm />
          <nldd-menu-item slot="overflow" text="Nieuwe taak" icon="plus"></nldd-menu-item>
        </nldd-toolbar-item>
      </nldd-toolbar>

      {/* Content */}
      {viewMode === 'list' ? (
        <TaskList tasks={filteredTasks} onEditTask={handleTaskClick} />
      ) : viewMode === 'board' ? (
        <TaskBoard tasks={filteredTasks} onEditTask={handleTaskClick} />
      ) : (
        <TaskPersonalView tasks={filteredTasks} onEditTask={handleTaskClick} />
      )}

      {/* Create form modal */}
      <TaskCreateForm
        open={showCreateForm}
        onClose={() => setShowCreateForm(false)}
        nodeId={defaultNodeId}
      />
    </nldd-container>
  );
}
