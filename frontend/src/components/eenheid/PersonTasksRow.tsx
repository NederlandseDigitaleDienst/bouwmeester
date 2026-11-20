import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { TaskCard } from '@/components/tasks/TaskCard';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { orUndef } from '@/components/nldd/events';
import { useTasksByPerson } from '@/hooks/useTasks';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import type { EenheidPersonTaskStats, Task } from '@/types';

interface PersonTasksRowProps {
  person: EenheidPersonTaskStats;
  isExpanded: boolean;
  onToggle: () => void;
}

/**
 * The expanded detail panel, spanning every column of the row's subgrid.
 * `nldd-table-row` uses `grid-template-columns: subgrid`, so a plain sibling
 * div of the cells with `grid-column: 1 / -1` spans the full row width — the
 * CSS-grid equivalent of the old `<td colSpan={5}>`. Same technique as
 * SyncStatusManager.tsx.
 */
function ExpandedPersonTasks({ person }: { person: EenheidPersonTaskStats }) {
  const { data: tasks, isLoading } = useTasksByPerson(person.person_id);
  const { openTaskDetail } = useTaskDetail();

  const handleTaskClick = (task: Task) => openTaskDetail(task.id);

  return (
    <div style={{ gridColumn: '1 / -1' }}>
      <nldd-container padding="12" gap="8">
        {isLoading && <LoadingSpinner padding="16" />}
        {tasks && tasks.length === 0 && (
          <nldd-text size="sm" color="secondary">
            <p>Geen taken gevonden.</p>
          </nldd-text>
        )}
        {tasks && tasks.length > 0 && (
          <nldd-container layout="stack" gap="8">
            {tasks.map((task) => (
              <TaskCard key={task.id} task={task} onEdit={handleTaskClick} compact />
            ))}
          </nldd-container>
        )}
      </nldd-container>
    </div>
  );
}

export function PersonTasksRow({ person, isExpanded, onToggle }: PersonTasksRowProps) {
  return (
    <nldd-table-row selected={orUndef(isExpanded)}>
      <nldd-cell>
        <nldd-container layout="row" gap="4" vertical-alignment="center">
          <NlddIconButton
            icon={isExpanded ? 'chevron-down' : 'chevron-right'}
            accessibleLabel={isExpanded ? 'Taken verbergen' : 'Taken tonen'}
            variant="neutral-transparent"
            size="sm"
            onClick={onToggle}
          />
          <nldd-text-cell text={person.person_naam} />
        </nldd-container>
      </nldd-cell>
      <nldd-text-cell text={String(person.open_count)} horizontal-alignment="right" hide-below="lg" />
      <nldd-text-cell
        text={String(person.in_progress_count)}
        horizontal-alignment="right"
        hide-below="lg"
      />
      <nldd-text-cell text={String(person.done_count)} horizontal-alignment="right" hide-below="lg" />
      <nldd-text-cell
        text={String(person.overdue_count)}
        horizontal-alignment="right"
        color={person.overdue_count > 0 ? 'critical' : 'secondary'}
      />
      {isExpanded && <ExpandedPersonTasks person={person} />}
    </nldd-table-row>
  );
}
