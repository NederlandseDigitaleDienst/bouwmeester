import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '@/components/nldd/Icon';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import { Modal } from '@/components/common/Modal';
import { Badge } from '@/components/common/Badge';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { ReferencesList } from '@/components/common/ReferencesList';
import { DetailSection } from '@/components/common/DetailSection';
import { DetailMetadataGrid } from '@/components/common/DetailMetadataGrid';
import { DetailModalFooter } from '@/components/common/DetailModalFooter';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { TaskEditForm } from './TaskEditForm';
import { TaskCreateForm } from './TaskCreateForm';
import { useTask, useReorderSubtasks } from '@/hooks/useTasks';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { useOpdrachtDetail } from '@/contexts/OpdrachtDetailContext';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { isOverdue as checkOverdue, formatDateLong, formatDateShort } from '@/utils/dates';
import {
  TaskStatus,
  TASK_STATUS_LABELS,
  TASK_STATUS_COLORS,
  TASK_PRIORITY_LABELS,
  TASK_PRIORITY_COLORS,
} from '@/types';
import type { TaskSubtask } from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

interface TaskDetailModalProps {
  taskId: string | null;
  open: boolean;
  onClose: () => void;
}

interface DetailLinkActionProps {
  text: string;
  startIcon: string;
  onClick: () => void;
}

/**
 * A metadata-grid value that opens something (a node, an opdracht, a
 * parlementair item) rather than navigating to a URL. `nldd-link` renders a
 * real `<a>`, and without an `href` the design system emits the anchor with no
 * `href` attribute at all — unfocusable, not keyboard-activatable, a link to
 * nowhere. There is genuinely nothing to link to here (these open an in-app
 * panel, not a URL), so this uses NlddButton in its lowest-emphasis variant
 * instead: a real, focusable, keyboard-operable control that reads like an
 * inline action rather than a link.
 */
function DetailLinkAction({ text, startIcon, onClick }: DetailLinkActionProps) {
  return (
    <NlddButton
      text={text}
      startIcon={startIcon}
      variant="neutral-transparent"
      size="sm"
      onClick={onClick}
    />
  );
}

interface SubtaskRowProps {
  subtask: TaskSubtask;
  canMoveUp: boolean;
  canMoveDown: boolean;
  reorderPending: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onOpen: () => void;
}

/**
 * A subtask row with three actions (move up, move down, open detail), so per
 * the list-with-rows pattern the row itself carries no href/button of its own
 * and each action gets its own nldd-list-item-segment. Refs + useNlddEvent
 * bind the clicks: a JSX onClick on a custom element is not a real listener
 * (React only delegates its fixed DOM event set), and disabled is boolean, so
 * it goes through orUndef the same as every other nldd-* boolean attribute.
 */
function SubtaskRow({
  subtask,
  canMoveUp,
  canMoveDown,
  reorderPending,
  onMoveUp,
  onMoveDown,
  onOpen,
}: SubtaskRowProps) {
  const upRef = useRef<HTMLElement>(null);
  const downRef = useRef<HTMLElement>(null);
  const openRef = useRef<HTMLElement>(null);
  useNlddEvent(upRef, 'click', onMoveUp);
  useNlddEvent(downRef, 'click', onMoveDown);
  useNlddEvent(openRef, 'click', onOpen);

  const subDone = subtask.status === TaskStatus.DONE;

  return (
    <nldd-list-item>
      <nldd-list-item-segment
        ref={upRef}
        button
        accessible-label="Omhoog"
        disabled={orUndef(!canMoveUp || reorderPending)}
      >
        <Icon name="chevron-up" size="xs" />
      </nldd-list-item-segment>
      <nldd-list-item-segment
        ref={downRef}
        button
        accessible-label="Omlaag"
        disabled={orUndef(!canMoveDown || reorderPending)}
      >
        <Icon name="chevron-down" size="xs" />
      </nldd-list-item-segment>
      <nldd-list-item-segment ref={openRef} button width="full">
        <nldd-icon-cell icon={subDone ? 'check-mark-circle' : 'circle'} color={subDone ? 'success' : 'content'} />
        <nldd-spacer-cell size="8" />
        <nldd-text-cell
          text={subtask.title}
          color={subDone ? 'secondary' : 'content'}
          width="fit-content"
        />
        {subtask.work_type && (
          <>
            <nldd-spacer-cell size="8" />
            <Badge color="donkerblauw">{subtask.work_type}</Badge>
          </>
        )}
        <nldd-spacer-cell size="flexible" />
        {subtask.assignee && (
          <nldd-text-cell text={subtask.assignee.naam} color="secondary" width="fit-content" size="sm" />
        )}
        {subtask.due_date && (
          <>
            <nldd-spacer-cell size="12" />
            <nldd-text-cell text={formatDateShort(subtask.due_date)} color="secondary" width="fit-content" size="sm" />
          </>
        )}
      </nldd-list-item-segment>
    </nldd-list-item>
  );
}

export function TaskDetailModal({ taskId, open, onClose }: TaskDetailModalProps) {
  const { data: task, isLoading } = useTask(taskId);
  const [showEdit, setShowEdit] = useState(false);
  const [showSubtaskCreate, setShowSubtaskCreate] = useState(false);
  const { openNodeDetail } = useNodeDetail();
  const { openOpdrachtDetail } = useOpdrachtDetail();
  const { openTaskDetail, taskParentLabel } = useTaskDetail();
  const navigate = useNavigate();
  const reorderSubtasks = useReorderSubtasks();

  const handleMoveSubtask = (index: number, direction: 'up' | 'down') => {
    if (!task) return;
    const subs = [...(task.subtasks ?? [])];
    const newIndex = direction === 'up' ? index - 1 : index + 1;
    if (newIndex < 0 || newIndex >= subs.length) return;
    [subs[index], subs[newIndex]] = [subs[newIndex], subs[index]];
    reorderSubtasks.mutate({ taskId: task.id, taskIds: subs.map((s) => s.id) });
  };

  if (!open) return null;

  if (showEdit && task) {
    return (
      <TaskEditForm
        open
        onClose={() => {
          setShowEdit(false);
          onClose();
        }}
        task={task}
      />
    );
  }

  const isOverdue =
    task?.due_date &&
    checkOverdue(task.due_date) &&
    task.status !== TaskStatus.DONE;

  const subtasks = task?.subtasks ?? [];
  const accentColor = task ? TASK_STATUS_COLORS[task.status] : undefined;

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title={isLoading ? 'Laden...' : task?.title ?? 'Taak niet gevonden'}
        size="lg"
        accentColor={accentColor}
        headerIcon={<Icon name="check-list" size="md" />}
        entityLabel="Taak"
        backLabel={taskParentLabel ?? undefined}
        onBack={taskParentLabel ? onClose : undefined}
        footer={
          <DetailModalFooter
            onClose={onClose}
            actions={
              <NlddButton
                variant="secondary"
                size="sm"
                startIcon="pencil"
                onClick={() => setShowEdit(true)}
                disabled={!task}
                text="Bewerken"
              />
            }
          />
        }
      >
        {isLoading ? (
          <LoadingSpinner padding="32" />
        ) : !task ? (
          <nldd-container layout="row" horizontal-alignment="center" vertical-alignment="center" padding-block="32">
            <nldd-text size="sm" color="secondary">Taak niet gevonden.</nldd-text>
          </nldd-container>
        ) : (
          <nldd-container gap="20">
            {/* Status / Priority / Deadline row */}
            <nldd-container layout="wrap" gap="8" vertical-alignment="center">
              <Badge color={TASK_STATUS_COLORS[task.status] ?? 'coolgray'} dot>
                {TASK_STATUS_LABELS[task.status]}
              </Badge>
              <Badge color={TASK_PRIORITY_COLORS[task.priority] ?? 'coolgray'} dot>
                {TASK_PRIORITY_LABELS[task.priority]}
              </Badge>
              {task.due_date && (
                <div className="hug">
                  <Icon name="clock" size="sm" />
                  <nldd-text size="sm" color={isOverdue ? 'critical' : 'secondary'} weight={isOverdue ? 'bold' : 'regular'}>
                    {formatDateLong(task.due_date)}
                  </nldd-text>
                </div>
              )}
            </nldd-container>

            {/* Description */}
            <DetailSection title="Beschrijving">
              <RichTextDisplay content={task.description} />
            </DetailSection>

            {/* References */}
            <ReferencesList targetId={task.id} />

            {/* Metadata grid */}
            <DetailMetadataGrid
              items={[
                {
                  label: 'Toegewezen aan',
                  value: task.assignee ? (
                    <nldd-container layout="row" gap="6" vertical-alignment="center">
                      {task.assignee.is_agent ? (
                        <nldd-icon icon="sparkles" size="20" color="paars" aria-hidden="true" />
                      ) : (
                        <Icon name="person" size="md" />
                      )}
                      <nldd-text size="sm">{task.assignee.naam}</nldd-text>
                    </nldd-container>
                  ) : (
                    <nldd-text size="sm" color="secondary">Niet toegewezen</nldd-text>
                  ),
                },
                {
                  label: 'Verantwoordelijke eenheid',
                  value: task.organisatie_eenheid ? (
                    <nldd-container layout="row" gap="6" vertical-alignment="center">
                      <Icon name="apartment-building" size="md" />
                      <nldd-text size="sm">{task.organisatie_eenheid.naam}</nldd-text>
                    </nldd-container>
                  ) : (
                    <nldd-text size="sm" color="secondary">Geen</nldd-text>
                  ),
                },
                {
                  label: 'Node',
                  value: task.node ? (
                    <DetailLinkAction
                      text={task.node.title}
                      startIcon="link"
                      onClick={() => openNodeDetail(task.node_id!, task.title)}
                    />
                  ) : (
                    <nldd-text size="sm" color="secondary">Geen</nldd-text>
                  ),
                },
                ...(task.opdracht
                  ? [
                      {
                        label: 'Opdracht',
                        value: (
                          <DetailLinkAction
                            text={task.opdracht.titel}
                            startIcon="clipboard-bullet-list"
                            onClick={() => openOpdrachtDetail(task.opdracht!.id, task.title)}
                          />
                        ),
                      },
                    ]
                  : []),
                ...(task.parlementair_item_id
                  ? [
                      {
                        label: 'Beoordeling',
                        value: (
                          <DetailLinkAction
                            text="Ga naar beoordeling"
                            startIcon="file-text"
                            onClick={() => {
                              onClose();
                              navigate(`/parlementair?item=${task.parlementair_item_id}`);
                            }}
                          />
                        ),
                      },
                    ]
                  : []),
                {
                  label: 'Aangemaakt',
                  value: formatDateLong(task.created_at),
                  icon: <Icon name="calendar" size="md" />,
                },
              ]}
            />

            {/* Subtasks */}
            <DetailSection
              title="Subtaken"
              icon={<Icon name="tree-structure" size="sm" />}
              count={subtasks.length}
              action={
                <NlddButton
                  variant="neutral-transparent"
                  size="sm"
                  startIcon="plus"
                  onClick={() => setShowSubtaskCreate(true)}
                  text="Subtaak toevoegen"
                />
              }
            >
              {subtasks.length > 0 ? (
                <nldd-list appearance="simple" accessible-label="Subtaken">
                  {subtasks.map((sub, idx) => (
                    <SubtaskRow
                      key={sub.id}
                      subtask={sub}
                      canMoveUp={idx > 0}
                      canMoveDown={idx < subtasks.length - 1}
                      reorderPending={reorderSubtasks.isPending}
                      onMoveUp={() => handleMoveSubtask(idx, 'up')}
                      onMoveDown={() => handleMoveSubtask(idx, 'down')}
                      onOpen={() => openTaskDetail(sub.id, task.title)}
                    />
                  ))}
                </nldd-list>
              ) : (
                <nldd-text size="sm" color="secondary">Geen subtaken</nldd-text>
              )}
            </DetailSection>
          </nldd-container>
        )}
      </Modal>

      {/* Subtask create form */}
      {task && (
        <TaskCreateForm
          open={showSubtaskCreate}
          onClose={() => setShowSubtaskCreate(false)}
          nodeId={task.node_id}
          parentId={task.id}
        />
      )}
    </>
  );
}
