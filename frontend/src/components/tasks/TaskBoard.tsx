import { useState } from 'react';
import { TaskCard } from './TaskCard';
import { useUpdateTask } from '@/hooks/useTasks';
import { TaskStatus, TASK_STATUS_LABELS } from '@/types';
import type { Task } from '@/types';

interface TaskBoardProps {
  tasks: Task[];
  onEditTask: (task: Task) => void;
}

const BOARD_COLUMNS: TaskStatus[] = [
  TaskStatus.OPEN,
  TaskStatus.IN_PROGRESS,
  TaskStatus.DONE,
];

/** Column accent, using the semantic roles rather than literal colors. */
type NlddBadgeColor = NonNullable<React.ComponentProps<'nldd-badge'>['color']>;

const COLUMN_TAG_COLOR: Record<TaskStatus, NlddBadgeColor> = {
  [TaskStatus.OPEN]: 'accent',
  [TaskStatus.IN_PROGRESS]: 'warning',
  [TaskStatus.DONE]: 'success',
  [TaskStatus.CANCELLED]: 'neutral',
};

export function TaskBoard({ tasks, onEditTask }: TaskBoardProps) {
  const updateTask = useUpdateTask();
  const [dragOverColumn, setDragOverColumn] = useState<TaskStatus | null>(null);

  const tasksByStatus = BOARD_COLUMNS.reduce(
    (acc, status) => {
      acc[status] = tasks.filter((t) => t.status === status);
      return acc;
    },
    {} as Record<TaskStatus, Task[]>,
  );

  const handleDragStart = (e: React.DragEvent, task: Task) => {
    e.dataTransfer.setData('text/plain', task.id);
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleDragOver = (e: React.DragEvent, status: TaskStatus) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverColumn(status);
  };

  const handleDragLeave = () => {
    setDragOverColumn(null);
  };

  const handleDrop = (e: React.DragEvent, targetStatus: TaskStatus) => {
    e.preventDefault();
    setDragOverColumn(null);
    const taskId = e.dataTransfer.getData('text/plain');
    const task = tasks.find((t) => t.id === taskId);
    if (!task || task.status === targetStatus) return;

    updateTask.mutate({
      id: taskId,
      data: { status: targetStatus },
    });
  };

  return (
    // Left as a plain div, deliberately: this frame is a horizontal-scroll
    // snap carousel on narrow screens that becomes a fixed 3-column grid at
    // md, with negative-margin edge-to-edge bleed below md. nldd-container's
    // `layout` is one fixed mode (no responsive stack->grid switch) and it has
    // no scroll-snap or negative-margin equivalent, so no composition of
    // components reproduces this without a full custom scroller.
    <div className="task-board">
      {BOARD_COLUMNS.map((status) => (
        // Left as a plain div: this is the native HTML5 drag-and-drop target
        // (onDragOver/onDragLeave/onDrop), which no nldd component models.
        // The drag-over highlight is likewise plain CSS state, not
        // something nldd-container/nldd-card can express as a boolean prop.
        <div
          key={status}
          onDragOver={(e) => handleDragOver(e, status)}
          onDragLeave={handleDragLeave}
          onDrop={(e) => handleDrop(e, status)}
          className={`task-board-column${dragOverColumn === status ? ' is-drag-over' : ''}`}
        >
          <nldd-container layout="row" gap="8" vertical-alignment="center" padding="16" padding-bottom="12">
            <nldd-text size="sm" weight="bold">
              {TASK_STATUS_LABELS[status]}
            </nldd-text>
            {/* Pushes the count badge to the far edge, the container-level
                equivalent of nldd-spacer-cell in a row of cells. */}
            <nldd-spacer size="flexible" direction="horizontal" />
            <nldd-badge color={COLUMN_TAG_COLOR[status]} number={tasksByStatus[status]?.length ?? 0} decorative />
          </nldd-container>

          <nldd-container gap="8" padding-inline="12" padding-bottom="12">
            {tasksByStatus[status]?.map((task) => (
              // Plain div: this is the native drag SOURCE (draggable + onDragStart).
              <div
                key={task.id}
                draggable
                onDragStart={(e) => handleDragStart(e, task)}
                className="draggable-card"
              >
                <TaskCard task={task} onEdit={onEditTask} compact />
              </div>
            ))}

            {(tasksByStatus[status]?.length ?? 0) === 0 && (
              // nldd-container has no min-height attribute (only nldd-cell and
              // a few section components do), so the empty-column height is an
              // inline style.
              <nldd-container layout="row" horizontal-alignment="center" vertical-alignment="center" style={{ minHeight: '100px' }}>
                <nldd-text size="xs" color="secondary">
                  Sleep taken hierheen
                </nldd-text>
              </nldd-container>
            )}
          </nldd-container>
        </div>
      ))}
    </div>
  );
}
