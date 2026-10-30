import { Badge } from '@/components/common/Badge';
import { Card } from '@/components/common/Card';
import { Icon } from '@/components/nldd/Icon';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { useUpdateTask } from '@/hooks/useTasks';
import {
  TaskStatus,
  TaskPriority,
  TASK_PRIORITY_LABELS,
  TASK_PRIORITY_COLORS,
  TASK_STATUS_LABELS,
} from '@/types';
import type { Task } from '@/types';
import { richTextToPlain } from '@/utils/richtext';
import { isOverdue as checkOverdue, formatDateShort } from '@/utils/dates';

interface TaskCardProps {
  task: Task;
  onEdit?: (task: Task) => void;
  compact?: boolean;
}

const priorityIcons: Record<TaskPriority, React.ReactNode> = {
  [TaskPriority.KRITIEK]: <Icon name="exclamation-triangle" size="sm" />,
  [TaskPriority.HOOG]: <Icon name="exclamation-triangle" size="sm" />,
  [TaskPriority.NORMAAL]: null,
  [TaskPriority.LAAG]: null,
};

/**
 * A task title that opens the task's editor.
 *
 * It opens an in-page editor rather than a URL, so `nldd-link` does not fit:
 * without an `href` the design system emits an `<a>` with no href at all,
 * which is neither focusable nor keyboard-operable. `nldd-button` does not fit
 * either: it renders only its `text` attribute, a plain string, so it cannot
 * carry the `nldd-text` that gives the title its weight and its done-state
 * color — and its control padding and min-size would box a title in.
 *
 * So this is a native button stripped by `plain-button`, which keeps the tab
 * stop, the focus ring and Enter/Space while leaving the title looking like a
 * title. Same treatment as the person name in PersonCardExpandable.
 *
 * The click is stopped here so it does not also reach the card's own onClick,
 * which listens on the host element and would open the task a second time.
 */
function TaskTitleButton({
  title,
  isDone,
  onOpen,
}: {
  title: string;
  isDone: boolean;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      className="plain-button"
      onClick={(e) => {
        e.stopPropagation();
        onOpen();
      }}
      style={{ textAlign: 'left', minWidth: 0 }}
    >
      <nldd-text size="sm" weight="medium" color={isDone ? 'secondary' : 'content'}>
        {title}
      </nldd-text>
    </button>
  );
}

export function TaskCard({ task, onEdit, compact = false }: TaskCardProps) {
  const updateTask = useUpdateTask();
  const isDone = task.status === TaskStatus.DONE;
  const isOverdue =
    task.due_date && checkOverdue(task.due_date) && !isDone;

  const subtasks = task.subtasks ?? [];
  const doneSubtasks = subtasks.filter((s) => s.status === TaskStatus.DONE).length;

  const handleToggleDone = () => {
    updateTask.mutate({
      id: task.id,
      data: {
        status: isDone ? TaskStatus.OPEN : TaskStatus.DONE,
      },
    });
  };

  const handleCardClick = () => {
    onEdit?.(task);
  };

  return (
    <Card
      hoverable={!!onEdit}
      onClick={onEdit ? handleCardClick : undefined}
    >
      <nldd-container layout="row" gap="12" vertical-alignment="top">
        {/* Checkbox */}
        <div onClick={(e) => e.stopPropagation()}>
          <NlddIconButton
            icon={isDone ? 'check-mark-circle' : 'circle'}
            variant="neutral-transparent"
            size="sm"
            accessibleLabel={isDone ? 'Markeer als niet afgerond' : 'Markeer als afgerond'}
            onClick={handleToggleDone}
          />
        </div>

        {/* Content */}
        <nldd-container width="full" gap="4">
          {/* The title is the operable element, not the card: the card holds
              the done-checkbox, and a control inside a button is invalid. The
              card's own onClick stays as a pointer convenience on top of it. */}
          {onEdit ? (
            <TaskTitleButton
              title={task.title}
              isDone={isDone}
              onOpen={handleCardClick}
            />
          ) : (
            <nldd-text size="sm" weight="medium" color={isDone ? 'secondary' : 'content'}>
              {task.title}
            </nldd-text>
          )}

          {!compact && task.description && (
            <nldd-text size="xs" color="secondary">
              {richTextToPlain(task.description)}
            </nldd-text>
          )}

          <nldd-container layout="wrap" gap="8" vertical-alignment="center">
            <Badge
              color={TASK_PRIORITY_COLORS[task.priority]}
              dot
            >
              {priorityIcons[task.priority]}
              {TASK_PRIORITY_LABELS[task.priority]}
            </Badge>

            {!compact && (
              <Badge color={isDone ? 'groen' : 'coolgray'}>
                {TASK_STATUS_LABELS[task.status]}
              </Badge>
            )}

            {task.due_date && (
              <div className="hug">
                <Icon name="clock" size="xs" />
                <nldd-text size="xs" color={isOverdue ? 'critical' : 'secondary'} weight={isOverdue ? 'bold' : 'regular'}>
                  {formatDateShort(task.due_date)}
                </nldd-text>
              </div>
            )}

            {task.assignee && (
              <div className="hug">
                {task.assignee.is_agent ? (
                  <nldd-icon icon="sparkles" size="16" color="paars" aria-hidden="true" />
                ) : (
                  <Icon name="person" size="xs" />
                )}
                <nldd-text size="xs" color="secondary">{task.assignee.naam}</nldd-text>
              </div>
            )}

            {task.organisatie_eenheid && (
              <div className="hug">
                <Icon name="apartment-building" size="xs" />
                <nldd-text size="xs" color="secondary">{task.organisatie_eenheid.naam}</nldd-text>
              </div>
            )}

            {task.work_type && (
              <Badge color="donkerblauw">{task.work_type}</Badge>
            )}

            {subtasks.length > 0 && (
              <div className="hug">
                <Icon name="tree-structure" size="xs" />
                <nldd-text size="xs" color="secondary">{doneSubtasks}/{subtasks.length}</nldd-text>
              </div>
            )}
          </nldd-container>
        </nldd-container>
      </nldd-container>
    </Card>
  );
}
