import { useEffect, useMemo, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import type { NLDDMoveEventDetail } from '@nldd/design-system/task-board';

import { Badge } from '@/components/common/Badge';
import { useNlddEvent } from '@/components/nldd/events';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useUpdateIssue } from '@/hooks/useIssues';
import { useTaakVerwijderen } from '@/hooks/useTaakVerwijderen';
import { useUpdateTask } from '@/hooks/useTasks';
import {
  IssueStatus,
  TaskStatus,
  issueSoortLabel,
  type BacklogIssue,
  type BacklogLosseTaak,
  type BacklogTask,
} from '@/types';
import { allesAfNa } from '@/utils/issueVoortgang';
import { DodModal } from './DodModal';
import { TaakKaart } from './InitiatiefBacklog';

/** De drie kolommen; een vraag staat in de kolom van zijn status. */
const KOLOMMEN: { status: TaskStatus; label: string }[] = [
  { status: TaskStatus.OPEN, label: 'Te doen' },
  { status: TaskStatus.IN_PROGRESS, label: 'In uitvoering' },
  { status: TaskStatus.DONE, label: 'Afgerond' },
];

const VRAAG_KOLOM: Record<IssueStatus, TaskStatus> = {
  [IssueStatus.OPEN]: TaskStatus.OPEN,
  [IssueStatus.IN_PROGRESS]: TaskStatus.IN_PROGRESS,
  [IssueStatus.DONE]: TaskStatus.DONE,
};

type Kaart =
  | { soort: 'vraag'; id: string; vraag: BacklogIssue }
  | { soort: 'taak'; id: string; taak: BacklogTask; vraag: BacklogIssue }
  | { soort: 'taak'; id: string; taak: BacklogLosseTaak; vraag: null };

/**
 * Het bord met al het werk: één kanban met de onderzoeksvragen als kort
 * kaartje en alle taken eronder, ook de taken zonder vraag. Handig voor wie
 * al zijn taken tegelijk wil zien: met het filter op taakeigenaar staan
 * alleen die taken erop, met de vragen waar ze onder hangen.
 *
 * Een vraag staat in de kolom van zijn status, zijn taken elk in de kolom van
 * hun eigen status. Binnen een kolom staan de kaartjes in de volgorde van de
 * lijst: per vraag eerst de vraag, dan zijn taken.
 *
 * Slepen werkt zoals in het kleine kanban onder een vraag (MiniKanban): een
 * taak krijgt de status van de kolom, en de Definition of Done volgt als de
 * laatste open taak van een vraag af is. Een
 * vraag naar Afgerond slepen opent de DoD; afronden gaat alleen daarmee. Een
 * vraag terug naar Te doen of In uitvoering zet zijn status.
 */
export function WerkBord({
  vragen,
  losseTaken,
  takenPerVraag,
  onOpenVraag,
}: {
  /** De vragen zoals de filters ze tonen; met een taakeigenaar alleen diens taken. */
  vragen: BacklogIssue[];
  losseTaken: BacklogLosseTaak[];
  /** Alle taken per vraag, ongefilterd: nodig om te zien of alles af is. */
  takenPerVraag: Map<string, BacklogTask[]>;
  onOpenVraag: (id: string) => void;
}) {
  const { openTaskDetail } = useTaskDetail();
  const verwijderen = useTaakVerwijderen();
  const updateTask = useUpdateTask();
  const updateIssue = useUpdateIssue();
  const bordRef = useRef<HTMLElement>(null);
  // De vraag waarvan de DoD open staat.
  const [dodVraag, setDodVraag] = useState<BacklogIssue | null>(null);

  const kaarten = useMemo<Kaart[]>(
    () => [
      ...vragen.flatMap((v): Kaart[] => [
        { soort: 'vraag', id: v.id, vraag: v },
        ...v.tasks.map((t): Kaart => ({ soort: 'taak', id: t.id, taak: t, vraag: v })),
      ]),
      ...losseTaken.map((t): Kaart => ({ soort: 'taak', id: t.id, taak: t, vraag: null })),
    ],
    [vragen, losseTaken],
  );

  // Kolom die net is gekozen maar nog niet terug is van de server.
  const [verplaatst, setVerplaatst] = useState<Record<string, TaskStatus>>({});
  const kolomVan = (k: Kaart): TaskStatus =>
    verplaatst[k.id] ?? (k.soort === 'vraag' ? VRAAG_KOLOM[k.vraag.status] : k.taak.status);
  useEffect(() => {
    setVerplaatst((prev) => {
      const rest = Object.fromEntries(
        Object.entries(prev).filter(([id, kolom]) => {
          const k = kaarten.find((x) => x.id === id);
          return k && (k.soort === 'vraag' ? VRAAG_KOLOM[k.vraag.status] : k.taak.status) !== kolom;
        }),
      );
      return Object.keys(rest).length === Object.keys(prev).length ? prev : rest;
    });
  }, [kaarten]);

  const terug = (id: string) =>
    setVerplaatst((prev) => {
      const { [id]: _weg, ...rest } = prev;
      return rest;
    });

  useNlddEvent(bordRef, 'nldd-move', (event) => {
    const { item, toColumn } = (event as CustomEvent<NLDDMoveEventDetail>).detail;
    const id = item.dataset.kaartId;
    const kaart = kaarten.find((k) => k.id === id);
    const kolom = toColumn as TaskStatus;
    if (!id || !kaart || kolomVan(kaart) === kolom) return;

    if (kaart.soort === 'vraag') {
      // Afronden alleen via de DoD; die zet de status zelf.
      if (kolom === TaskStatus.DONE) {
        setDodVraag(kaart.vraag);
        return;
      }
      setVerplaatst((prev) => ({ ...prev, [id]: kolom }));
      updateIssue.mutate(
        { plek: kaart.vraag, issueId: id, data: { status: kolom as unknown as IssueStatus } },
        { onError: () => terug(id) },
      );
      return;
    }

    // Een taak: zoals in het kleine kanban.
    const hadFocus = item.contains(document.activeElement);
    flushSync(() => setVerplaatst((prev) => ({ ...prev, [id]: kolom })));
    if (hadFocus) {
      requestAnimationFrame(() => {
        // De wikkel draagt het id; het kaartje erin krijgt de focus.
        const wikkel = bordRef.current?.querySelector<HTMLElement>(`[data-kaart-id="${id}"]`);
        (wikkel?.querySelector<HTMLElement>('[tabindex]') ?? wikkel)?.focus();
      });
    }
    const vraag = kaart.vraag;
    const alle = vraag ? (takenPerVraag.get(vraag.id) ?? vraag.tasks) : [];
    const naDod =
      vraag && vraag.status !== IssueStatus.DONE && allesAfNa(alle, id, kolom) ? () => setDodVraag(vraag) : undefined;
    updateTask.mutate(
      { id, data: { status: kolom } },
      {
        onSuccess: () => naDod?.(),
        onError: () => terug(id),
      },
    );
  });

  return (
    <>
      <nldd-task-board ref={bordRef} accessible-label="Alle onderzoeksvragen en taken">
        {KOLOMMEN.map((kolom) => (
          <nldd-task-board-column key={kolom.status} value={kolom.status} text={kolom.label}>
            {kaarten
              .filter((k) => kolomVan(k) === kolom.status)
              .map((k) =>
                k.soort === 'vraag' ? (
                  <VraagKaart key={k.id} vraag={k.vraag} alle={takenPerVraag.get(k.id) ?? k.vraag.tasks} onOpen={() => onOpenVraag(k.id)} />
                ) : (
                  <div key={k.id} data-kaart-id={k.id}>
                    <TaakKaart
                      task={k.taak}
                      {...(k.vraag ? { vraagTitel: k.vraag.title } : { losOpCasus: k.taak.casus.title })}
                      onOpen={(waar) => openTaskDetail(k.taak.id, k.vraag?.title ?? k.taak.title, waar)}
                      onContextMenu={(e) => verwijderen.openMenu(e, k.taak)}
                    />
                  </div>
                ),
              )}
          </nldd-task-board-column>
        ))}
      </nldd-task-board>
      {verwijderen.element}
      <DodModal issue={dodVraag} mode="afronden" onClose={() => setDodVraag(null)} />
    </>
  );
}

/**
 * Een onderzoeksvraag in het kort: soort, de vraag, hoeveel taken af zijn en
 * waar hij bij hoort. Klikken opent het vraagpaneel.
 */
function VraagKaart({ vraag, alle, onOpen }: { vraag: BacklogIssue; alle: BacklogTask[]; onOpen: () => void }) {
  const af = alle.filter((t) => t.status === TaskStatus.DONE).length;
  return (
    <div
      className="bord-vraagkaart"
      data-kaart-id={vraag.id}
      data-af={vraag.status === IssueStatus.DONE ? '' : undefined}
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen();
        }
      }}
    >
      <nldd-container gap="4">
        <div className="hug hug-gap-8">
          <Badge color={vraag.is_onderzoeksvraag ? 'oranje' : 'coolgray'}>{issueSoortLabel(vraag)}</Badge>
          <nldd-text size="xs" color="secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {af}/{alle.length}
            <span className="visually-hidden"> taken af</span>
          </nldd-text>
        </div>
        {/* Kort: na drie regels af, de hele vraag in de tooltip en het paneel. */}
        <nldd-text size="sm" weight="medium" className="bord-vraagtitel" title={vraag.title}>
          {vraag.title}
        </nldd-text>
        <nldd-text size="xs" color="secondary" className="bord-vraagregel">
          {vraag.casus?.title ?? 'Zonder casus'}
        </nldd-text>
      </nldd-container>
    </div>
  );
}
