import { useMemo } from 'react';
import { Icon } from '@/components/nldd/Icon';
import { TaskCard } from './TaskCard';
import { TaskStatus } from '@/types';
import type { Task } from '@/types';

interface TaskPersonalViewProps {
  tasks: Task[];
  onEditTask: (task: Task) => void;
}

interface TaskGroup {
  key: string;
  label: string;
  icon: React.ReactNode;
  tasks: Task[];
  /** nldd-text color for the group header; unset falls back to 'content'. */
  headerColor?: 'critical';
}

export function TaskPersonalView({ tasks, onEditTask }: TaskPersonalViewProps) {
  const groups = useMemo<TaskGroup[]>(() => {
    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const todayEnd = new Date(todayStart);
    todayEnd.setDate(todayEnd.getDate() + 1);
    const weekEnd = new Date(todayStart);
    weekEnd.setDate(weekEnd.getDate() + 8); // end of "next 7 days after today"

    const overdue: Task[] = [];
    const today: Task[] = [];
    const thisWeek: Task[] = [];
    const later: Task[] = [];

    for (const task of tasks) {
      const isDone = task.status === TaskStatus.DONE || task.status === TaskStatus.CANCELLED;

      if (!task.due_date) {
        later.push(task);
        continue;
      }

      const dueDate = new Date(task.due_date);

      if (dueDate < todayStart && !isDone) {
        overdue.push(task);
      } else if (dueDate >= todayStart && dueDate < todayEnd) {
        today.push(task);
      } else if (dueDate >= todayEnd && dueDate < weekEnd) {
        thisWeek.push(task);
      } else {
        later.push(task);
      }
    }

    return [
      {
        key: 'overdue',
        label: 'Verlopen',
        icon: <Icon name="exclamation-triangle" size="md" />,
        tasks: overdue,
        headerColor: 'critical' as const,
      },
      {
        key: 'today',
        label: 'Vandaag',
        icon: <Icon name="calendar-event" size="md" />,
        tasks: today,
      },
      {
        key: 'week',
        label: 'Deze week',
        icon: <Icon name="calendar" size="md" />,
        tasks: thisWeek,
      },
      {
        key: 'later',
        label: 'Later',
        icon: <Icon name="clock" size="md" />,
        tasks: later,
      },
    ];
  }, [tasks]);

  return (
    <nldd-container gap="24">
      {groups.map((group) =>
        group.tasks.length > 0 ? (
          <section key={group.key}>
            <nldd-container layout="row" gap="8" vertical-alignment="center" padding-bottom="12">
              {group.icon}
              <nldd-text size="sm" weight="bold" {...(group.headerColor ? { color: group.headerColor } : {})}>
                {group.label}
              </nldd-text>
              <nldd-badge color="neutral" number={group.tasks.length} decorative />
            </nldd-container>
            <nldd-container gap="8">
              {group.tasks.map((task) => (
                <TaskCard key={task.id} task={task} onEdit={onEditTask} />
              ))}
            </nldd-container>
          </section>
        ) : null,
      )}

      {/* Empty state when no tasks at all */}
      {groups.every((g) => g.tasks.length === 0) && (
        <nldd-container padding-block="16" horizontal-alignment="center">
          <nldd-text size="sm" color="secondary">
            <p>Geen taken gevonden.</p>
          </nldd-text>
        </nldd-container>
      )}
    </nldd-container>
  );
}
