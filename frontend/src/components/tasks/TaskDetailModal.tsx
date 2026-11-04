import { useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '@/components/nldd/Icon';
import { Select } from '@/components/common/Select';
import { TaskCommentsSection } from './TaskCommentsSection';
import { TaskAttachmentsSection } from './TaskAttachmentsSection';
import { usePeople } from '@/hooks/usePeople';
import { Modal } from '@/components/common/Modal';
import { ReferencesList } from '@/components/common/ReferencesList';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { Input } from '@/components/common/Input';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Eigenschap, Eigenschappen, TekstVeld, TitelVeld } from '@/components/common/DetailVelden';
import { useReorderSubtasks, useTask, useUpdateTask, useWorkTypes } from '@/hooks/useTasks';
import { DetailSection } from '@/components/common/DetailSection';
import { Badge } from '@/components/common/Badge';
import { TaskCreateForm } from './TaskCreateForm';
import { useTaakVerwijderen } from '@/hooks/useTaakVerwijderen';
import { useTaskFormOptions } from '@/hooks/useTaskFormOptions';
import { eventValue, orUndef, useNlddEvent } from '@/components/nldd/events';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { useOpdrachtDetail } from '@/contexts/OpdrachtDetailContext';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { isOverdue as checkOverdue, formatDateLong, formatDateShort } from '@/utils/dates';
import {
  TaskStatus,
  TaskPriority,
  TASK_STATUS_LABELS,
  TASK_STATUS_COLORS,
  TASK_PRIORITY_LABELS,
} from '@/types';
import type { Task, TaskSubtask, TaskUpdate } from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

const STATUS_OPTIONS = Object.values(TaskStatus).map((value) => ({ value, label: TASK_STATUS_LABELS[value] }));
const PRIORITY_OPTIONS = Object.values(TaskPriority).map((value) => ({ value, label: TASK_PRIORITY_LABELS[value] }));

interface TaskDetailModalProps {
  taskId: string | null;
  open: boolean;
  onClose: () => void;
  /** Midden (standaard), of als paneel links of rechts naast een bord. */
  placement?: 'center' | 'left' | 'right';
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

/** De deadline als datumveld; opslaan zodra er een datum staat of hij leeg is. */
function DeadlineVeld({ datum, teLaat, onOpslaan }: { datum: string; teLaat: boolean; onOpslaan: (datum: string | null) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', (e) => {
    const waarde = eventValue(e);
    if (waarde !== datum) onOpslaan(waarde || null);
  });
  return (
    <>
      <Input ref={ref} type="date" aria-label="Deadline" value={datum} />
      {teLaat && <nldd-text size="xs" color="critical" weight="bold">Over de deadline</nldd-text>}
    </>
  );
}

/** Node van een taak: kiezen, en openen met het pijltje. */
function NodeVeld({ task, onOpslaan, onOpen }: { task: Task; onOpslaan: (nodeId: string) => void; onOpen: () => void }) {
  const { nodeOptions } = useTaskFormOptions();
  return (
    <nldd-container layout="row" gap="4" vertical-alignment="center">
      <nldd-container className="row-fill">
        <CreatableSelect
          value={task.node_id ?? ''}
          onChange={(v) => v && v !== task.node_id && onOpslaan(v)}
          options={nodeOptions}
          placeholder="Koppel aan een node"
        />
      </nldd-container>
      {task.node_id && (
        <NlddIconButton icon="external-link" accessibleLabel="Node openen" variant="neutral-transparent" size="sm" onClick={onOpen} />
      )}
    </nldd-container>
  );
}

/** Werktype, zoals in het bewerkformulier op main: kiezen, nieuw maken of leeg. */
function WerktypeVeld({ task, onOpslaan }: { task: Task; onOpslaan: (werktype: string | null) => void }) {
  const { data: workTypes = [] } = useWorkTypes();
  return (
    <CreatableSelect
      value={task.work_type ?? ''}
      onChange={(v) => (v || null) !== (task.work_type ?? null) && onOpslaan(v || null)}
      options={workTypes.map((wt) => ({ value: wt, label: wt }))}
      placeholder="bijv. Analyse, Overleg, Review..."
      onCreate={async (text) => {
        onOpslaan(text);
        return text;
      }}
      createLabel="Nieuw werktype"
      onClear={task.work_type ? () => onOpslaan(null) : undefined}
    />
  );
}

/**
 * Eén subtaak in de lijst, zoals op main: omhoog, omlaag, en openen. Een
 * subtaak is een gewone taak met eigen kenmerken; die staan op de regel.
 */
function SubtaakRij({
  subtask,
  kanOmhoog,
  kanOmlaag,
  bezig,
  onOmhoog,
  onOmlaag,
  onOpen,
}: {
  subtask: TaskSubtask;
  kanOmhoog: boolean;
  kanOmlaag: boolean;
  bezig: boolean;
  onOmhoog: () => void;
  onOmlaag: () => void;
  onOpen: () => void;
}) {
  const upRef = useRef<HTMLElement>(null);
  const downRef = useRef<HTMLElement>(null);
  const openRef = useRef<HTMLElement>(null);
  useNlddEvent(upRef, 'click', onOmhoog);
  useNlddEvent(downRef, 'click', onOmlaag);
  useNlddEvent(openRef, 'click', onOpen);
  const af = subtask.status === TaskStatus.DONE;
  return (
    <nldd-list-item>
      <nldd-list-item-segment ref={upRef} button accessible-label="Omhoog" disabled={orUndef(!kanOmhoog || bezig)}>
        <Icon name="chevron-up" size="xs" />
      </nldd-list-item-segment>
      <nldd-list-item-segment ref={downRef} button accessible-label="Omlaag" disabled={orUndef(!kanOmlaag || bezig)}>
        <Icon name="chevron-down" size="xs" />
      </nldd-list-item-segment>
      <nldd-list-item-segment ref={openRef} button width="full">
        <nldd-icon-cell icon={af ? 'check-mark-circle' : 'circle'} color={af ? 'success' : 'content'} />
        <nldd-spacer-cell size="8" />
        <nldd-text-cell text={subtask.title} color={af ? 'secondary' : 'content'} width="fit-content" />
        {subtask.work_type && (
          <>
            <nldd-spacer-cell size="8" />
            <Badge color="donkerblauw">{subtask.work_type}</Badge>
          </>
        )}
        <nldd-spacer-cell size="flexible" />
        {subtask.assignee && <nldd-text-cell text={subtask.assignee.naam} color="secondary" width="fit-content" size="sm" />}
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

/**
 * De subtaken van een taak, zoals op main: een lijst met
 * omhoog en omlaag, en Subtaak toevoegen opent het formulier voor een
 * nieuwe taak onder deze.
 */
function Subtaken({ task }: { task: Task }) {
  const reorder = useReorderSubtasks();
  const { openTaskDetail } = useTaskDetail();
  const [nieuw, setNieuw] = useState(false);
  const subtasks = task.subtasks ?? [];
  const verplaats = (index: number, richting: -1 | 1) => {
    const nieuwIndex = index + richting;
    if (nieuwIndex < 0 || nieuwIndex >= subtasks.length) return;
    const ids = subtasks.map((s) => s.id);
    [ids[index], ids[nieuwIndex]] = [ids[nieuwIndex], ids[index]];
    reorder.mutate({ taskId: task.id, taskIds: ids });
  };
  return (
    <DetailSection
      title="Subtaken"
      icon={<Icon name="tree-structure" size="sm" />}
      count={subtasks.length}
      action={<NlddButton variant="neutral-transparent" size="sm" startIcon="plus" onClick={() => setNieuw(true)} text="Subtaak toevoegen" />}
    >
      {subtasks.length > 0 ? (
        <nldd-list appearance="simple" accessible-label="Subtaken">
          {subtasks.map((sub, i) => (
            <SubtaakRij
              key={sub.id}
              subtask={sub}
              kanOmhoog={i > 0}
              kanOmlaag={i < subtasks.length - 1}
              bezig={reorder.isPending}
              onOmhoog={() => verplaats(i, -1)}
              onOmlaag={() => verplaats(i, 1)}
              onOpen={() => openTaskDetail(sub.id, task.title)}
            />
          ))}
        </nldd-list>
      ) : (
        <nldd-text size="sm" color="secondary">Geen subtaken</nldd-text>
      )}
      <TaskCreateForm open={nieuw} onClose={() => setNieuw(false)} nodeId={task.node_id ?? undefined} parentId={task.id} />
    </DetailSection>
  );
}

function EenheidVeld({ task, onOpslaan }: { task: Task; onOpslaan: (eenheidId: string | null) => void }) {
  const { eenheidOptions } = useTaskFormOptions();
  return (
    <Select
      size="sm"
      aria-label="Verantwoordelijke eenheid"
      options={eenheidOptions.map((o) => ({ value: o.value, label: o.label }))}
      value={task.organisatie_eenheid_id ?? ''}
      onChange={(e) => onOpslaan(e.target.value || null)}
    />
  );
}

/**
 * Alles van één taak, direct te bewerken: geen knop Bewerken, geen apart
 * formulier. Keuzelijsten en de datum slaan meteen op, de beschrijving met
 * Opslaan. De titel bewerk je in de kop, via het potloodje. Opnieuw gemount
 * per taak, zodat half getypte tekst niet bij een andere taak terechtkomt.
 */
function TaakVelden({ task, onClose }: { task: Task; onClose: () => void }) {
  const updateTask = useUpdateTask();
  const zet = (data: TaskUpdate) => updateTask.mutate({ id: task.id, data });
  const { openNodeDetail } = useNodeDetail();
  const { openOpdrachtDetail } = useOpdrachtDetail();
  const navigate = useNavigate();
  // Iedereen die actief is; staat er iemand op de taak die dat niet meer
  // is, dan blijft die zichtbaar zodat de keuze niet stil verspringt.
  const { data: mensen } = usePeople();
  const personOptions = useMemo(() => {
    const opties = [
      { value: '', label: 'Niemand' },
      ...(mensen ?? []).filter((p) => p.is_active && !p.is_agent).map((p) => ({ value: p.id, label: p.naam })),
    ];
    if (task.assignee && !opties.some((o) => o.value === task.assignee!.id)) {
      opties.push({ value: task.assignee.id, label: task.assignee.naam });
    }
    return opties;
  }, [mensen, task.assignee]);

  const teLaat = !!task.due_date && checkOverdue(task.due_date) && task.status !== TaskStatus.DONE;

  const bewaarBeschrijving = async (tekst: string | null) => {
    try {
      await updateTask.mutateAsync({ id: task.id, data: { description: tekst } });
    } catch {
      // de melding is al getoond; de tekst blijft staan
    }
  };

  return (
    <nldd-container gap="24">
      <nldd-container gap="12">
        <Eigenschappen>
          <Eigenschap label="Status">
            <Select size="sm" aria-label="Status" options={STATUS_OPTIONS} value={task.status} onChange={(e) => zet({ status: e.target.value as TaskStatus })} />
          </Eigenschap>
          <Eigenschap label="Prioriteit">
            <Select size="sm" aria-label="Prioriteit" options={PRIORITY_OPTIONS} value={task.priority} onChange={(e) => zet({ priority: e.target.value as TaskPriority })} />
          </Eigenschap>
          <Eigenschap label="Toegewezen aan">
            <Select size="sm" aria-label="Toegewezen aan" options={personOptions} value={task.assignee_id ?? ''} onChange={(e) => zet({ assignee_id: e.target.value || null })} />
          </Eigenschap>
          <Eigenschap label="Deadline">
            <DeadlineVeld datum={task.due_date?.split('T')[0] ?? ''} teLaat={teLaat} onOpslaan={(due_date) => zet({ due_date })} />
          </Eigenschap>
          <Eigenschap label="Verantwoordelijke eenheid">
            <EenheidVeld task={task} onOpslaan={(organisatie_eenheid_id) => zet({ organisatie_eenheid_id })} />
          </Eigenschap>
          <Eigenschap label="Werktype">
            <WerktypeVeld task={task} onOpslaan={(work_type) => zet({ work_type })} />
          </Eigenschap>
          {/* De node is te kiezen, ook bij een subtaak. */}
          <Eigenschap label="Node" breed>
            <NodeVeld task={task} onOpslaan={(node_id) => zet({ node_id })} onOpen={() => openNodeDetail(task.node_id!, task.title)} />
          </Eigenschap>
          {task.opdracht && (
            <Eigenschap label="Opdracht">
              <div>
                <DetailLinkAction
                  text={task.opdracht.titel}
                  startIcon="clipboard-bullet-list"
                  onClick={() => openOpdrachtDetail(task.opdracht!.id, task.title)}
                />
              </div>
            </Eigenschap>
          )}
          {task.parlementair_item_id && (
            <Eigenschap label="Beoordeling">
              <div>
                <DetailLinkAction
                  text="Ga naar beoordeling"
                  startIcon="file-text"
                  onClick={() => {
                    onClose();
                    navigate(`/parlementair?item=${task.parlementair_item_id}`);
                  }}
                />
              </div>
            </Eigenschap>
          )}
        </Eigenschappen>
        <nldd-text size="xs" color="secondary">
          Aangemaakt {formatDateLong(task.created_at)}
          {task.updated_at ? `, laatst bijgewerkt ${formatDateLong(task.updated_at)}` : ''}
        </nldd-text>
      </nldd-container>

      <TekstVeld
        label="Beschrijving en notities"
        placeholder="Wat moet er gebeuren, wanneer is het af, en wat wil je onthouden? Gebruik @ om iemand te noemen."
        tekst={task.description ?? ''}
        bezig={updateTask.isPending}
        onOpslaan={bewaarBeschrijving}
      />

      <Subtaken task={task} />

      {/* Opmerkingen: het gesprek over de taak. */}
      <TaskCommentsSection taskId={task.id} />

      {/* Verwijzingen, als die er zijn */}
      <ReferencesList targetId={task.id} />
    </nldd-container>
  );
}

export function TaskDetailModal({ taskId, open, onClose, placement = 'center' }: TaskDetailModalProps) {
  const { data: task, isLoading } = useTask(taskId);
  const { taskParentLabel } = useTaskDetail();
  // Verwijderen staat onderaan; daarna is er niets meer om te tonen.
  const { vraagBevestiging, element: verwijderen } = useTaakVerwijderen({ onVerwijderd: onClose });
  // Welke taak er een open titelveld heeft (via het potloodje in de kop). Een
  // id en geen boolean: open je een andere taak, dan is het veld vanzelf dicht.
  const [titelVan, setTitelVan] = useState<string | null>(null);
  const updateTask = useUpdateTask();

  if (!open) return null;

  const accentColor = task ? TASK_STATUS_COLORS[task.status] : undefined;
  // Als zijpaneel naast een bord is er niets om naar terug te gaan: terug
  // zou hetzelfde doen als Sluiten. In het midden, gestapeld op een ander
  // venster, wel.
  const terug = placement === 'center' && taskParentLabel ? taskParentLabel : undefined;

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title={isLoading ? 'Laden...' : task?.title ?? 'Taak niet gevonden'}
        size="lg"
        placement={placement}
        accentColor={accentColor}
        headerIcon={<Icon name="check-list" size="md" />}
        backLabel={terug}
        onBack={terug ? onClose : undefined}
        dismissText="Sluit"
        // Het potloodje maakt van de titel in de kop meteen een invoerveld.
        titleEditor={
          task && titelVan === task.id ? (
            <TitelVeld
              key={task.id}
              titel={task.title}
              zonderLabel
              onOpslaan={(title) => updateTask.mutate({ id: task.id, data: { title } })}
              onKlaar={() => setTitelVan(null)}
            />
          ) : undefined
        }
        toolbar={
          task ? (
            <NlddIconButton
              slot="toolbar"
              icon="pencil"
              accessibleLabel="Titel bewerken"
              variant="neutral-transparent"
              size="sm"
              onClick={() => setTitelVan(task.id)}
            />
          ) : undefined
        }
      >
        {isLoading ? (
          <LoadingSpinner padding="32" />
        ) : !task ? (
          <nldd-container layout="row" horizontal-alignment="center" vertical-alignment="center" padding-block="32">
            <nldd-text size="sm" color="secondary">Taak niet gevonden.</nldd-text>
          </nldd-container>
        ) : (
          <nldd-container gap="24">
            <TaakVelden key={task.id} task={task} onClose={onClose} />
            {/* De onderste regel: bestanden met Uploaden, en links Verwijderen
                van de taak. Verwijderen is niet terug te draaien en vraagt
                eerst om bevestiging. */}
            <TaskAttachmentsSection
              taskId={task.id}
              acties={
                <NlddButton
                  variant="neutral-transparent"
                  size="sm"
                  startIcon="trash"
                  onClick={() => vraagBevestiging({ id: task.id, title: task.title })}
                  text="Verwijderen"
                />
              }
            />
          </nldd-container>
        )}
      </Modal>
      {verwijderen}
    </>
  );
}
