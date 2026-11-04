import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal, flushSync } from 'react-dom';
import type { NLDDMoveEventDetail } from '@nldd/design-system/task-board';
import { useNavigate } from 'react-router-dom';

import { Badge } from '@/components/common/Badge';
import { EmptyState } from '@/components/common/EmptyState';
import { Input } from '@/components/common/Input';
import { IssueAanmakenModal } from './IssueAanmakenModal';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Select } from '@/components/common/Select';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { useNlddEvent } from '@/components/nldd/events';
import { useBacklog } from '@/hooks/useCasussen';
import { InitiatiefIdContext } from '@/hooks/useInitiatiefPersonOptions';
import { useTaskDetail, type TaskDetailPlacement } from '@/contexts/TaskDetailContext';
import { Icon } from '@/components/nldd/Icon';
import { useCreateTask, useUpdateTask } from '@/hooks/useTasks';
import {
  ISSUE_STATUS_COLORS,
  ISSUE_STATUS_LABELS,
  IssueStatus,
  TaskStatus,
  issueSoortLabel,
  type BacklogIssue,
  type BacklogLosseTaak,
  type BacklogTask,
} from '@/types';
import { useTaakVerwijderen } from '@/hooks/useTaakVerwijderen';
import { initiatiefPath } from '@/utils/initiatiefRoutes';
import { IssueDetailModal } from './IssueDetailModal';
import { DodModal } from './DodModal';
import { allesAfNa } from '@/utils/issueVoortgang';
import { faseNaam, useCasusFases } from '@/hooks/useCasusFases';

/**
 * De tab Backlog: alle issues van alle casussen van het initiatief in één
 * lijst, omgekeerd aan de casusweergave. Een issue is een onderzoeksvraag;
 * eronder hangen de taken, met hun subtaken op het kaartje. Een issue klapt
 * open naar een klein kanban met drie
 * kolommen, naar het voorbeeld van een Jira-bord: taken schuif je met de muis
 * van kolom naar kolom.
 *
 * Filteren en sorteren gebeurt in de browser: de backend geeft de hele
 * backlog van het initiatief, die is klein genoeg.
 *
 * Met `vasteCasusId` is het het werk van één casus: zo staat het in het
 * casusoverzicht op de tab Casussen, in hetzelfde formaat. Dan geen
 * casusfilter, geen casuslink per issue en geen sorteren op casus.
 */

type SortKey = 'casus' | 'status';
const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'casus', label: 'Casus' },
  { value: 'status', label: 'Status' },
];

/** 'lopend' = alles behalve afgerond; los van IssueStatus.OPEN ('open'). */
type StatusFilter = 'lopend' | 'alles' | IssueStatus;
const STATUS_FILTER_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: 'lopend', label: 'Open werk' },
  { value: 'alles', label: 'Alles' },
  ...Object.entries(ISSUE_STATUS_LABELS).map(([value, label]) => ({ value: value as IssueStatus, label })),
];

/** Filterwaarde voor taken zonder eigenaar; geen geldig persoons-id. */
const GEEN_EIGENAAR = '__geen__';

const STATUS_ORDER: Record<IssueStatus, number> = {
  [IssueStatus.IN_PROGRESS]: 0,
  [IssueStatus.OPEN]: 1,
  [IssueStatus.DONE]: 2,
};

/** De drie kolommen van het mini-kanban, met de taakstatus erachter. */
const KOLOMMEN: { status: TaskStatus; label: string }[] = [
  { status: TaskStatus.OPEN, label: 'Te doen' },
  { status: TaskStatus.IN_PROGRESS, label: 'In uitvoering' },
  { status: TaskStatus.DONE, label: 'Afgerond' },
];

/** Stabiele basisvolgorde, dezelfde als de casusweergave: casus, dan volgorde. */
function baseCompare(a: BacklogIssue, b: BacklogIssue): number {
  return a.casus.title.localeCompare(b.casus.title, 'nl') || a.sort_order - b.sort_order || a.created_at.localeCompare(b.created_at);
}

function compareBy(key: SortKey): (a: BacklogIssue, b: BacklogIssue) => number {
  switch (key) {
    case 'status':
      return (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || baseCompare(a, b);
    case 'casus':
    default:
      return baseCompare;
  }
}

export function InitiatiefBacklog({
  initiatiefId,
  vasteCasusId,
  filterPlek,
}: {
  initiatiefId: string;
  vasteCasusId?: string;
  /**
   * Per casus staan Status en Taakeigenaar in de kop van de tab Casussen,
   * naast Casuseigenaar en Casus. Dit is de plek daarvoor; zonder plek staan
   * ze hier zelf, boven de lijst.
   */
  filterPlek?: HTMLElement | null;
}) {
  const { data, isLoading } = useBacklog(initiatiefId);
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('lopend');
  const [gekozenCasus, setCasusId] = useState('');
  const casusId = vasteCasusId ?? gekozenCasus;
  const [eigenaar, setEigenaar] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('casus');
  // Het issue in het detailpaneel; uit de lijst gehaald, zodat het na elke
  // wijziging de nieuwe stand toont (en dicht gaat als het weg is).
  const [detailId, setDetailId] = useState<string | null>(null);
  const [issueToevoegen, setIssueToevoegen] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Met een vaste casus is de rest van de backlog er niet: ook de tellers en
  // de keuzes voor taakeigenaar gaan dan alleen over deze casus.
  const issues = useMemo(
    () => (data?.issues ?? []).filter((i) => !vasteCasusId || i.casus.id === vasteCasusId),
    [data, vasteCasusId],
  );
  const losseTaken = useMemo(
    () => (data?.losse_taken ?? []).filter((t) => !vasteCasusId || t.casus.id === vasteCasusId),
    [data, vasteCasusId],
  );
  // De volledige takenlijst per issue, los van het filter op taakeigenaar:
  // nodig om te zien of na een sleepactie alles af is.
  const takenPerIssue = useMemo(() => new Map(issues.map((i) => [i.id, i.tasks])), [issues]);
  // De casus openen is naar de tab Casussen gaan, niet een venster.
  const openCasus = (id: string) => navigate(`${initiatiefPath(initiatiefId, 'casussen')}?casus=${id}`);

  const casusOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const i of issues) seen.set(i.casus.id, i.casus.title);
    for (const t of losseTaken) seen.set(t.casus.id, t.casus.title);
    return [
      { value: '', label: 'Alle casussen' },
      ...[...seen].sort((a, b) => a[1].localeCompare(b[1], 'nl')).map(([value, label]) => ({ value, label })),
    ];
  }, [issues, losseTaken]);

  // Wie taken heeft in deze backlog: de keuzes voor het filter op
  // taakeigenaar. Uit de taken zelf, zodat elke keuze iets oplevert.
  const eigenaarOptions = useMemo(() => {
    const seen = new Map<string, string>();
    let zonder = false;
    for (const t of [...issues.flatMap((i) => i.tasks), ...losseTaken]) {
      if (t.assignee_id && t.assignee) seen.set(t.assignee_id, t.assignee.naam);
      else zonder = true;
    }
    return [
      { value: '', label: 'Iedereen' },
      ...[...seen].sort((a, b) => a[1].localeCompare(b[1], 'nl')).map(([value, label]) => ({ value, label })),
      ...(zonder ? [{ value: GEEN_EIGENAAR, label: 'Niet toegewezen' }] : []),
    ];
  }, [issues, losseTaken]);
  const vanEigenaar = useCallback(
    (t: { assignee_id?: string | null }) =>
      !eigenaar || (eigenaar === GEEN_EIGENAAR ? !t.assignee_id : t.assignee_id === eigenaar),
    [eigenaar],
  );

  const rows = useMemo(() => {
    const out = issues
      .filter((i) => {
        if (statusFilter === 'lopend' ? i.status === IssueStatus.DONE : statusFilter !== 'alles' && i.status !== statusFilter) return false;
        if (casusId && i.casus.id !== casusId) return false;
        if (eigenaar && !i.tasks.some(vanEigenaar)) return false;
        return true;
      })
      // Met een taakeigenaar gekozen toont het kanban alleen diens taken.
      .map((i) => (eigenaar ? { ...i, tasks: i.tasks.filter(vanEigenaar) } : i));
    return out.sort(compareBy(sortKey));
  }, [issues, statusFilter, casusId, eigenaar, vanEigenaar, sortKey]);

  const losseRows = useMemo(
    () =>
      losseTaken.filter(
        (t) => (!casusId || t.casus.id === casusId) && (statusFilter !== 'lopend' || t.status !== TaskStatus.DONE) && vanEigenaar(t),
      ),
    [losseTaken, casusId, statusFilter, vanEigenaar],
  );

  // De stand van de backlog, los van de filters.
  const openIssues = issues.filter((i) => i.status !== IssueStatus.DONE);
  const openTaken = issues.flatMap((i) => i.tasks).filter((t) => t.status !== TaskStatus.DONE).length;

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allOpen = rows.length > 0 && rows.every((r) => expanded.has(r.id));

  if (isLoading) return <LoadingSpinner padding="32" />;

  // In de kop van de tab Casussen is minder ruimte: daar iets smaller.
  const filters = (
    <>
      <Select compact label="Status" size="sm" width={filterPlek ? '140px' : '150px'} options={STATUS_FILTER_OPTIONS} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as StatusFilter)} />
      {!vasteCasusId && (
        <Select compact label="Casus" size="sm" width="220px" options={casusOptions} value={casusId} onChange={(e) => setCasusId(e.target.value)} />
      )}
      <Select compact label="Taakeigenaar" size="sm" width={filterPlek ? '180px' : '200px'} options={eigenaarOptions} value={eigenaar} onChange={(e) => setEigenaar(e.target.value)} />
      {!vasteCasusId && (
        <Select compact label="Sorteer op" size="sm" width="150px" options={SORT_OPTIONS} value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)} />
      )}
    </>
  );
  // Een onderzoeksvraag mag hier ontstaan zonder taken eronder.
  const toevoegen = (
    <NlddButton variant="secondary" size="sm" startIcon="plus" onClick={() => setIssueToevoegen(true)} text="Onderzoeksvraag toevoegen" />
  );

  return (
    <InitiatiefIdContext.Provider value={initiatiefId}>
    <nldd-container gap="16" padding={vasteCasusId ? '0' : '16'}>
      {/* De kop in twee regels zonder lege ruimte: de filters met rechts
          Onderzoeksvraag toevoegen, daaronder de stand met Alles uitklappen.
          Per casus staan de filters in de kop van de tab, en past de rest op
          één regel. */}
      <nldd-container gap="8">
        {filterPlek ? (
          createPortal(filters, filterPlek)
        ) : (
          <nldd-container layout="wrap" gap="8" vertical-alignment="bottom">
            {filters}
            <nldd-spacer direction="horizontal" size="flexible" />
            {toevoegen}
          </nldd-container>
        )}
        <nldd-container layout="wrap" gap="8" vertical-alignment="center">
          {/* De stand van de backlog, los van de filters, naast wat je ziet. */}
          <div className="hug hug-gap-8">
            <Badge color="oranje">{openIssues.length} open onderzoeksvragen</Badge>
            <Badge color="lintblauw">{openTaken} open taken</Badge>
            <nldd-text size="xs" color="secondary">{rows.length} van {issues.length} onderzoeksvragen</nldd-text>
          </div>
          <nldd-spacer direction="horizontal" size="flexible" />
          <NlddButton
            variant="neutral-transparent"
            size="sm"
            startIcon={allOpen ? 'chevron-up' : 'chevron-down'}
            onClick={() => setExpanded(allOpen ? new Set() : new Set(rows.map((r) => r.id)))}
            text={allOpen ? 'Alles inklappen' : 'Alles uitklappen'}
          />
          {filterPlek && toevoegen}
        </nldd-container>
      </nldd-container>

      {rows.length === 0 ? (
        <EmptyState
          title={issues.length === 0 ? 'Nog geen onderzoeksvragen' : 'Geen onderzoeksvragen in deze selectie'}
          description={issues.length === 0 ? 'Voeg er een toe met Onderzoeksvraag toevoegen.' : 'Pas de filters aan.'}
        />
      ) : (
        <nldd-container gap="8">
          {rows.map((issue) => (
            <IssueRow
              key={issue.id}
              issue={issue}
              alleTaken={takenPerIssue.get(issue.id) ?? issue.tasks}
              open={expanded.has(issue.id)}
              onToggle={() => toggle(issue.id)}
              onOpenCasus={vasteCasusId ? undefined : () => openCasus(issue.casus.id)}
              onOpen={() => setDetailId(issue.id)}
            />
          ))}
        </nldd-container>
      )}

      {losseRows.length > 0 && (
        <LosseTaken taken={losseRows} issues={issues} />
      )}

      <IssueDetailModal issue={issues.find((i) => i.id === detailId) ?? null} onClose={() => setDetailId(null)} />
      <IssueAanmakenModal open={issueToevoegen} onClose={() => setIssueToevoegen(false)} initiatiefId={initiatiefId} casusId={casusId || undefined} />
    </nldd-container>
    </InitiatiefIdContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Issue-rij met mini-kanban
// ---------------------------------------------------------------------------

interface IssueRowProps {
  issue: BacklogIssue;
  /** Alle taken van het issue, ook als het kanban gefilterd is. */
  alleTaken: BacklogTask[];
  open: boolean;
  onToggle: () => void;
  /** Zonder: geen casuslink (in het overzicht van één casus). */
  onOpenCasus?: () => void;
  /** Het detailpaneel openen: daar staat alles wat je aan het issue doet. */
  onOpen: () => void;
}

/**
 * Eén issue. Links onder elkaar wat je ervan wilt weten (soort, eigenaar,
 * casus, hoe het ervoor staat), rechts de titel over de rest van de breedte:
 * de vraag is wat je leest, dus die krijgt de ruimte. Op een smalle rij komt
 * de kolom boven de titel (`issue-rij` in utilities.css). Afronden,
 * bewerken, verwijderen en de toelichting staan in het detailpaneel, achter
 * het icoontje rechts; uitklappen toont alleen het kanban.
 */
function IssueRow({ issue, alleTaken, open, onToggle, onOpenCasus, onOpen }: IssueRowProps) {
  const casusRef = useRef<HTMLElement>(null);
  useNlddEvent(casusRef, 'click', useCallback(() => onOpenCasus?.(), [onOpenCasus]));

  // Alleen wat af is telt: "1/4" zegt genoeg.
  const af = issue.tasks.filter((t) => t.status === TaskStatus.DONE).length;
  const totaal = issue.tasks.length;
  const fase = faseNaam(useCasusFases(useContext(InitiatiefIdContext)), issue.casus.fase);
  const klaar = issue.status === IssueStatus.DONE;

  // Sleep je de laatste open taak naar Afgerond, dan volgt meteen de DoD.
  const [dod, setDod] = useState<'afronden' | null>(null);

  return (
    <div
      className="issue-kader"
      style={{
        border: '1px solid var(--primitives-color-neutral-200)',
        borderLeft: `4px solid var(--primitives-color-${klaar ? 'neutral-300' : 'accent-300'})`,
        borderRadius: 'var(--semantics-surfaces-corner-radius)',
      }}
    >
      <nldd-container layout="row" gap="8" vertical-alignment="top" padding="12">
        <NlddIconButton
          icon={open ? 'chevron-down' : 'chevron-right'}
          accessibleLabel={open ? `${issue.title}: inklappen` : `${issue.title}: uitklappen`}
          variant="neutral-transparent"
          size="sm"
          onClick={onToggle}
        />
        <div className="issue-rij">
          {/* Links wie het trekt en hoever het is. */}
          <div className="issue-rij-meta">
            <div className="hug">
              <Icon name="person" size="sm" />
              <nldd-text size="xs" color={issue.assignee ? 'content' : 'secondary'}>
                {issue.assignee?.naam ?? 'Geen trekker'}
              </nldd-text>
            </div>
            {/* Kort: "1/9" is 1 van 9 taken af, met een smalle balk erbij. */}
            <div className="hug hug-gap-8" title={`${af} van ${totaal} taken af`}>
              <Icon name="check-list" size="sm" />
              <nldd-text size="xs" color="secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>
                {af}/{totaal}
                <span className="visually-hidden"> taken af</span>
              </nldd-text>
              {totaal > 0 && (
                <nldd-progress-bar
                  value={af}
                  max={totaal}
                  size="sm"
                  color={af === totaal ? 'success' : 'accent'}
                  value-display="none"
                  accessible-label={`${af} van ${totaal} taken af`}
                  style={{ width: '64px' }}
                />
              )}
            </div>
          </div>
          <nldd-text size="md" weight="medium" className="issue-rij-titel" style={klaar ? { opacity: 0.7 } : undefined}>
            {issue.title}
          </nldd-text>
          {/* Rechts, tegen de rand: wat het is en de status naast elkaar, de
              casus eronder. */}
          <div className="issue-rij-stand">
            <div className="hug hug-gap-8">
              <Badge color={issue.is_onderzoeksvraag ? 'oranje' : 'coolgray'}>{issueSoortLabel(issue)}</Badge>
              <Badge color={ISSUE_STATUS_COLORS[issue.status]}>{ISSUE_STATUS_LABELS[issue.status]}</Badge>
            </div>
            {/* De fase van de casus als tooltip: zo blijft de kolom rustig. */}
            {onOpenCasus && (
              <nldd-link ref={casusRef} size="xs" text={issue.casus.title} title={`Fase: ${fase}`} style={{ cursor: 'pointer' }} />
            )}
          </div>
        </div>
        {/* Eén ingang voor alles wat je aan het issue zelf doet: de drie
            puntjes openen het volledige paneel. */}
        <NlddIconButton
          icon="ellipsis"
          accessibleLabel={`${issue.title}: openen`}
          variant="neutral-transparent"
          size="sm"
          onClick={onOpen}
        />
      </nldd-container>
      {open && (
        <>
          <MiniKanban issue={issue} alleTaken={alleTaken} onAllesAf={klaar ? undefined : () => setDod('afronden')} />
        </>
      )}
      <DodModal issue={dod ? issue : null} mode="afronden" onClose={() => setDod(null)} />
    </div>
  );
}

/**
 * Het takenbord onder een uitgeklapte onderzoeksvraag: `nldd-task-board` met
 * drie kolommen, de taakstatussen Te doen, In uitvoering en Afgerond.
 * Geannuleerd ("Ingetrokken" in het design system) krijgt geen kolom.
 *
 * Verplaatsen kan op drie manieren, die het bord alle drie als `nldd-move`
 * meldt: slepen, Alt met de pijltjes op een kaartje, en de status in het
 * taakdetail (de weg zonder slepen). Het bord verplaatst zelf niets. De
 * handler zet de nieuwe status meteen in een lokale stand, met `flushSync`
 * zodat het kaartje er staat voordat het bord de focus teruggeeft, en slaat
 * hem daarna op. Lukt opslaan niet, dan gaat het kaartje terug en meldt de
 * toast waarom. Alleen de kolom wordt bewaard: de volgorde binnen een kolom
 * heeft geen veld in de taak.
 *
 * Sleep je de laatste open taak naar Afgerond, dan komt meteen de
 * DoD-checklist (`onAllesAf`): alle taken af maakt de vraag nog niet af, de
 * DoD doet dat.
 */
function MiniKanban({
  issue,
  alleTaken,
  onAllesAf,
}: {
  issue: BacklogIssue;
  alleTaken: BacklogTask[];
  /** Alleen meegegeven zolang de vraag niet af is. */
  onAllesAf?: () => void;
}) {
  const { openTaskDetail } = useTaskDetail();
  const verwijderen = useTaakVerwijderen();
  const updateTask = useUpdateTask();
  const createTask = useCreateTask();
  const [nieuw, setNieuw] = useState('');
  const bordRef = useRef<HTMLElement>(null);

  // Status die net is verplaatst maar nog niet terug is van de server.
  const [verplaatst, setVerplaatst] = useState<Record<string, TaskStatus>>({});
  const statusVan = (t: BacklogTask) => verplaatst[t.id] ?? t.status;
  // Zodra de server dezelfde status geeft, is de lokale stand niet meer nodig.
  useEffect(() => {
    setVerplaatst((prev) => {
      const rest = Object.fromEntries(
        Object.entries(prev).filter(([id, status]) => issue.tasks.find((t) => t.id === id)?.status !== status),
      );
      return Object.keys(rest).length === Object.keys(prev).length ? prev : rest;
    });
  }, [issue.tasks]);

  useNlddEvent(bordRef, 'nldd-move', (event) => {
    const { item, toColumn } = (event as CustomEvent<NLDDMoveEventDetail>).detail;
    const id = item.dataset.taakId;
    const task = issue.tasks.find((t) => t.id === id);
    const status = toColumn as TaskStatus;
    if (!id || !task || statusVan(task) === status) return;

    // React zet het kaartje in een nieuwe kolom neer als een nieuw element; het
    // bord geeft de focus alleen terug aan het oude. Dat doen we dus zelf.
    const hadFocus = item.contains(document.activeElement);
    flushSync(() => setVerplaatst((prev) => ({ ...prev, [id]: status })));
    if (hadFocus) {
      requestAnimationFrame(() => bordRef.current?.querySelector<HTMLElement>(`[data-taak-id="${id}"]`)?.focus());
    }

    const vraagDoD = onAllesAf && allesAfNa(alleTaken, id, status);
    updateTask.mutate(
      { id, data: { status } },
      {
        // Pas na een geslaagde wijziging; bij een fout toont de toast het al.
        onSuccess: () => (vraagDoD ? onAllesAf() : undefined),
        onError: () =>
          setVerplaatst((prev) => {
            const { [id]: _weg, ...rest } = prev;
            return rest;
          }),
      },
    );
  });

  const voegToe = async () => {
    const title = nieuw.trim();
    if (!title) return;
    try {
      await createTask.mutateAsync({ title, issue_id: issue.id });
      setNieuw('');
    } catch {
      // toast is al getoond
    }
  };

  return (
    <div style={{ borderTop: '1px solid var(--primitives-color-neutral-200)', padding: '8px' }}>
      <nldd-task-board ref={bordRef} accessible-label={`Taken bij ${issue.title}`}>
        {KOLOMMEN.map((kolom) => (
          <nldd-task-board-column key={kolom.status} value={kolom.status} text={kolom.label}>
            {issue.tasks
              .filter((t) => statusVan(t) === kolom.status)
              .map((t) => (
                <TaakKaart
                  key={t.id}
                  task={t}
                  onOpen={(waar) => openTaskDetail(t.id, issue.title, waar)}
                  onContextMenu={(e) => verwijderen.openMenu(e, t)}
                />
              ))}
            {/* Een nieuwe taak begint in Te doen, dus daar staat het veld. */}
            {kolom.status === TaskStatus.OPEN && (
              <nldd-container slot="footer" layout="row" gap="6" vertical-alignment="center">
                <nldd-container className="row-fill">
                  <Input
                    type="text"
                    value={nieuw}
                    onChange={(e) => setNieuw(e.target.value)}
                    placeholder="Nieuwe taak bij deze onderzoeksvraag"
                    aria-label={`Nieuwe taak op ${issue.title}`}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void voegToe();
                    }}
                  />
                </nldd-container>
                <NlddIconButton icon="plus" accessibleLabel="Taak toevoegen" size="sm" variant="neutral-transparent" onClick={() => void voegToe()} />
              </nldd-container>
            )}
          </nldd-task-board-column>
        ))}
      </nldd-task-board>
      {verwijderen.element}
    </div>
  );
}

/**
 * Eén taak als kaartje op het takenbord. Slepen zet de status (dat doet het
 * bord, zie MiniKanban); klikken of Enter opent het taakdetail,
 * waar wie, prioriteit, opmerkingen en bijlagen staan. Op het kaartje zelf
 * alleen een icoon met de naam van wie eraan werkt, niets te bedienen.
 *
 * Het detail opent als paneel aan de kant tegenover het kaartje: staat het
 * kaartje links op het scherm (te doen), dan komt het paneel rechts, en
 * andersom (afgerond). Zo blijft het kaartje in beeld.
 *
 * Rechtermuisknop opent een menu om de taak te verwijderen, met bevestiging.
 */
function TaakKaart({
  task,
  onOpen,
  onContextMenu,
}: {
  task: BacklogTask;
  onOpen: (waar: TaskDetailPlacement) => void;
  onContextMenu: (e: React.MouseEvent) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const open = () => {
    const rect = ref.current?.getBoundingClientRect();
    const midden = rect ? rect.left + rect.width / 2 : 0;
    onOpen(midden < window.innerWidth / 2 ? 'right' : 'left');
  };

  return (
    <div
      ref={ref}
      data-taak-id={task.id}
      role="button"
      tabIndex={0}
      onClick={open}
      onContextMenu={onContextMenu}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          open();
        }
      }}
      style={{
        background: 'var(--semantics-surfaces-base-background-color)',
        border: '1px solid var(--primitives-color-neutral-200)',
        borderRadius: 'var(--semantics-surfaces-corner-radius)',
        padding: '8px',
        cursor: 'pointer',
      }}
    >
      <nldd-container gap="4">
        {/* Afgerond blijft gewoon leesbaar: de kolom zegt al dat het af is. */}
        <nldd-text size="sm">{task.title}</nldd-text>
        <nldd-container layout="row" gap="6" vertical-alignment="center">
          {task.assignee?.is_agent ? (
            <nldd-icon icon="sparkles" size="16" color="paars" aria-hidden="true" />
          ) : (
            <nldd-icon icon="person" size="16" aria-hidden="true" />
          )}
          <nldd-text size="xs" color="secondary">{task.assignee?.naam ?? 'Niet toegewezen'}</nldd-text>
          {task.due_date && <nldd-text size="xs" color="secondary">· {task.due_date}</nldd-text>}
          <nldd-spacer direction="horizontal" size="flexible" />
          <OpmerkingenTeller aantal={task.comment_count} />
        </nldd-container>
      </nldd-container>
    </div>
  );
}

/**
 * Hoe besproken een taak is: een tekstballon met het aantal opmerkingen.
 * Zonder opmerkingen niets, zodat de kaartjes rustig blijven.
 */
function OpmerkingenTeller({ aantal }: { aantal: number }) {
  if (!aantal) return null;
  const tekst = aantal === 1 ? '1 opmerking' : `${aantal} opmerkingen`;
  return (
    <div className="hug hug-gap-2" title={tekst}>
      <nldd-icon icon="message-rectangle-text" size="16" aria-hidden="true" />
      <nldd-text size="xs" color="secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>
        {aantal}
        <span className="visually-hidden"> {aantal === 1 ? 'opmerking' : 'opmerkingen'}</span>
      </nldd-text>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Taken zonder issue
// ---------------------------------------------------------------------------

function LosseTaken({ taken, issues }: { taken: BacklogLosseTaak[]; issues: BacklogIssue[] }) {
  const updateTask = useUpdateTask();
  const verwijderen = useTaakVerwijderen();
  return (
    <nldd-container gap="8">
      <nldd-title size={6}><h3>Taken zonder onderzoeksvraag ({taken.length})</h3></nldd-title>
      <nldd-text size="xs" color="secondary">
        Liever niet: een taak hoort onder een issue. Hang ze hier onder een issue van dezelfde casus.
      </nldd-text>
      {taken.map((t) => {
        const kandidaten = issues.filter((i) => i.casus_id === t.casus_id);
        return (
          <div key={t.id} onContextMenu={(e) => verwijderen.openMenu(e, t)}>
          <nldd-container layout="row" gap="8" vertical-alignment="center">
            <nldd-container gap="2" className="row-fill">
              <nldd-text size="sm">{t.title}</nldd-text>
              <nldd-text size="xs" color="secondary">
                {t.casus.title}
              </nldd-text>
            </nldd-container>
            <OpmerkingenTeller aantal={t.comment_count} />
            {kandidaten.length > 0 && (
              <Select
                size="xs"
                width="280px"
                aria-label={`Hang ${t.title} onder een onderzoeksvraag`}
                options={[
                  { value: '', label: 'Hang onder onderzoeksvraag...' },
                  ...kandidaten.map((i) => ({ value: i.id, label: i.title })),
                ]}
                value=""
                onChange={(e) => {
                  if (e.target.value) updateTask.mutate({ id: t.id, data: { issue_id: e.target.value } });
                }}
              />
            )}
          </nldd-container>
          </div>
        );
      })}
      {verwijderen.element}
    </nldd-container>
  );
}
