import { useContext, useMemo, useState } from 'react';

import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { Eigenschap, Eigenschappen, TekstVeld, TitelVeld, Waarde } from '@/components/common/DetailVelden';
import { Modal } from '@/components/common/Modal';
import { Select } from '@/components/common/Select';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { useCasus, useCasussen } from '@/hooks/useCasussen';
import { InitiatiefIdContext, useInitiatiefPersonOptions } from '@/hooks/useInitiatiefPersonOptions';
import { useDeleteIssue, useUpdateIssue } from '@/hooks/useIssues';
import {
  ISSUE_STATUS_COLORS,
  ISSUE_STATUS_LABELS,
  IssueStatus,
  TaskStatus,
  issueSoortLabel,
  type BacklogIssue,
  type IssueUpdate,
} from '@/types';
import { DodModal } from './DodModal';
import { OnderzoeksvraagVinkje } from './OnderzoeksvraagVinkje';

const STATUS_OPTIONS = Object.values(IssueStatus).map((value) => ({ value, label: ISSUE_STATUS_LABELS[value] }));

interface Props {
  issue: BacklogIssue | null;
  onClose: () => void;
}

/**
 * Het overzicht van één onderzoeksvraag (of ander issue), als paneel aan de
 * rechterkant, net als het taakdetail. Alles direct te bewerken: de titel via
 * het potloodje, keuzelijsten slaan meteen op, de toelichting met Opslaan.
 * Afronden loopt via de Definition of Done, ook als je de status op
 * afgerond zet: alleen daarmee wordt een vraag af. Verhuizen naar een andere
 * casus kan alleen binnen het initiatief; de taken gaan mee. Verwijderen
 * staat onderaan en vraagt om bevestiging.
 */
export function IssueDetailModal({ issue, onClose }: Props) {
  if (!issue) return null;
  // Opnieuw mounten per issue, zodat half getypte tekst niet bij een ander
  // issue terechtkomt.
  return <Paneel key={issue.id} issue={issue} onClose={onClose} />;
}

function Paneel({ issue, onClose }: { issue: BacklogIssue; onClose: () => void }) {
  const initiatiefId = useContext(InitiatiefIdContext);
  const update = useUpdateIssue();
  const deleteIssue = useDeleteIssue();
  const personOptions = useInitiatiefPersonOptions(issue.assignee ?? null);
  const { data: casussen, isSuccess: casussenGeladen } = useCasussen(initiatiefId ?? undefined);
  const { data: casus } = useCasus(issue.casus_id);
  const [titelOpen, setTitelOpen] = useState(false);
  const [dod, setDod] = useState<'afronden' | 'bekijken' | null>(null);
  const [verwijderen, setVerwijderen] = useState(false);

  const zet = (data: IssueUpdate) => update.mutate({ casusId: issue.casus_id, issueId: issue.id, data });
  const bewaarToelichting = async (tekst: string | null) => {
    try {
      await update.mutateAsync({ casusId: issue.casus_id, issueId: issue.id, data: { toelichting: tekst } });
    } catch {
      // de melding is al getoond; de tekst blijft staan
    }
  };

  const klaar = issue.status === IssueStatus.DONE;
  const af = issue.tasks.filter((t) => t.status === TaskStatus.DONE).length;
  const dodItems = casus?.dod_items ?? [];
  const dodAf = dodItems.filter((i) => issue.dod_checked.includes(i)).length;

  // Alleen casussen van hetzelfde initiatief; de huidige staat er altijd in.
  const casusOptions = useMemo(() => {
    const opties = (casussen ?? [])
      .filter((c) => initiatiefId && c.initiatief_id === initiatiefId)
      .map((c) => ({ value: c.id, label: c.title }))
      .sort((a, b) => a.label.localeCompare(b.label, 'nl'));
    if (!opties.some((o) => o.value === issue.casus_id)) opties.unshift({ value: issue.casus_id, label: issue.casus.title });
    return opties;
  }, [casussen, initiatiefId, issue.casus_id, issue.casus.title]);

  const zetStatus = (status: IssueStatus) => {
    if (status === issue.status) return;
    // Afgerond alleen via de DoD; de checklist zet de status zelf.
    if (status === IssueStatus.DONE) setDod('afronden');
    else zet({ status });
  };
  // Heropenen: terug naar waar het werk staat; de volgende taakwijziging
  // rekent de status toch opnieuw uit.
  const heropenen = () => zet({ status: af > 0 ? IssueStatus.IN_PROGRESS : IssueStatus.OPEN });

  return (
    <>
      <Modal
        open
        onClose={onClose}
        title={issue.title}
        size="lg"
        placement="right"
        accentColor={ISSUE_STATUS_COLORS[issue.status]}
        dismissText="Sluit"
        toolbar={
          <NlddIconButton
            slot="toolbar"
            icon="pencil"
            accessibleLabel="Titel bewerken"
            variant="neutral-transparent"
            size="sm"
            onClick={() => setTitelOpen(true)}
          />
        }
      >
        <nldd-container gap="24">
          {/* De hele vraag: in de kop wordt een lange vraag afgekapt. */}
          {titelOpen ? (
            <TitelVeld titel={issue.title} onOpslaan={(title) => zet({ title })} onKlaar={() => setTitelOpen(false)} />
          ) : (
            <nldd-text size="md" weight="medium">{issue.title}</nldd-text>
          )}

          {/* Afronden of heropenen bovenaan: dat is wat je hier het vaakst komt doen. */}
          <nldd-container layout="row" gap="8" vertical-alignment="center">
            {klaar ? (
              <NlddButton variant="secondary" size="sm" onClick={heropenen} text="Heropenen" />
            ) : (
              <NlddButton size="sm" startIcon="check-mark" onClick={() => setDod('afronden')} text="Afronden" />
            )}
            {klaar && dodItems.length > 0 && (
              <button type="button" className="plain-button" onClick={() => setDod('bekijken')}>
                <nldd-text size="xs" color={dodAf < dodItems.length ? 'critical' : 'secondary'}>
                  DoD {dodAf}/{dodItems.length}
                </nldd-text>
              </button>
            )}
          </nldd-container>

          <Eigenschappen>
            <Eigenschap label="Status">
              <Select size="sm" aria-label="Status" options={STATUS_OPTIONS} value={issue.status} onChange={(e) => zetStatus(e.target.value as IssueStatus)} />
            </Eigenschap>
            <Eigenschap label="Issue-eigenaar">
              <Select size="sm" aria-label="Issue-eigenaar" options={personOptions} value={issue.assignee_id ?? ''} onChange={(e) => zet({ assignee_id: e.target.value || null })} />
            </Eigenschap>
            <Eigenschap label="Taken af">
              <Waarde>
                {af} van {issue.tasks.length}
              </Waarde>
            </Eigenschap>
            <Eigenschap label="Soort" breed>
              <Waarde>{issueSoortLabel(issue)}</Waarde>
              <OnderzoeksvraagVinkje checked={issue.is_onderzoeksvraag} onChange={(is_onderzoeksvraag) => zet({ is_onderzoeksvraag })} />
            </Eigenschap>
            {/* Volle breedte: casusnamen zijn lang. Opnieuw tekenen zodra de
                casussen binnen zijn, de dropdown ververst zijn label niet als
                alleen de opties veranderen. */}
            <Eigenschap label="Casus" breed>
              <Select
                key={casussenGeladen ? 'geladen' : 'laden'}
                size="sm"
                aria-label="Casus"
                options={casusOptions}
                value={issue.casus_id}
                disabled={!casussenGeladen}
                onChange={(e) => e.target.value !== issue.casus_id && zet({ casus_id: e.target.value })}
              />
              <nldd-text size="xs" color="secondary">Verhuis je de vraag naar een andere casus, dan gaan de taken mee.</nldd-text>
            </Eigenschap>
          </Eigenschappen>

          <TekstVeld
            label="Toelichting"
            placeholder="Waarom deze vraag, wat hoort erbij, wat is de context?"
            tekst={issue.toelichting ?? ''}
            bezig={update.isPending}
            onOpslaan={bewaarToelichting}
          />

          {/* Onderaan, los van de rest: verwijderen is niet terug te draaien. */}
          <div>
            <NlddButton variant="neutral-transparent" size="sm" startIcon="trash" onClick={() => setVerwijderen(true)} text="Verwijderen" />
          </div>
        </nldd-container>
      </Modal>
      <DodModal issue={dod ? issue : null} mode={dod ?? 'bekijken'} onClose={() => setDod(null)} />
      <ConfirmDialog
        open={verwijderen}
        onClose={() => setVerwijderen(false)}
        onConfirm={async () => {
          try {
            await deleteIssue.mutateAsync({ casusId: issue.casus_id, issueId: issue.id });
            setVerwijderen(false);
            onClose();
          } catch {
            // toast is al getoond
          }
        }}
        title="Verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={deleteIssue.isPending}
      >
        {`"${issue.title}" wordt verwijderd. De taken eronder blijven staan in dezelfde casus, als taken zonder onderzoeksvraag.`}
      </ConfirmDialog>
    </>
  );
}
