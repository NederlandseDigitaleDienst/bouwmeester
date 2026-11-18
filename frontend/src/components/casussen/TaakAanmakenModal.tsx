import { useState } from 'react';

import { Input } from '@/components/common/Input';
import { Modal } from '@/components/common/Modal';
import { Select } from '@/components/common/Select';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { useInitiatiefPersonOptions } from '@/hooks/useInitiatiefPersonOptions';
import { vraagtEigenaar } from '@/contexts/OpNaamContext';
import { useCreateTask } from '@/hooks/useTasks';
import { TASK_STATUS_LABELS, TaskStatus, type Task } from '@/types';

interface Props {
  open: boolean;
  onClose: () => void;
  /** De onderzoeksvraag waar de taak onder komt. */
  issue: { id: string; title: string };
  /** De kolom waar je op Taak toevoegen klikte; de taak begint daar. */
  status?: TaskStatus;
  /** De naam van die kolom zoals op het bord ("Te doen"). */
  kolomNaam?: string;
  /** Na een gelukte aanmaak, met de nieuwe taak. */
  onAangemaakt?: (taak: Task) => void;
}

/**
 * Een taak toevoegen onder een onderzoeksvraag, vanaf de knop onderaan een
 * kolom van het takenbord. Klein gehouden: wat er moet gebeuren, en in In
 * uitvoering en Afgerond meteen wie het doet. De rest (deadline,
 * beschrijving) staat in het taakdetail.
 *
 * De taak krijgt de status van de kolom. Een taak in Te doen staat nog niet
 * op naam, dus daar vraagt het venster niet naar een eigenaar. In In
 * uitvoering en Afgerond werkt er kennelijk al iemand aan: dan staat de
 * eigenaar alvast op jou, als je lid bent van het initiatief. Op Niemand
 * zetten mag.
 *
 * Wie hier te kiezen is, volgt de regel van de casus: alleen leden van het
 * initiatief (uit InitiatiefIdContext).
 */
export function TaakAanmakenModal({ open, ...props }: Props) {
  if (!open) return null;
  // Elke keer een leeg formulier.
  return <Formulier {...props} />;
}

function Formulier({ onClose, issue, status = TaskStatus.OPEN, kolomNaam, onAangemaakt }: Omit<Props, 'open'>) {
  const create = useCreateTask();
  const personOptions = useInitiatiefPersonOptions();
  const { currentPerson } = useCurrentPerson();
  const [titel, setTitel] = useState('');
  const metEigenaar = vraagtEigenaar(status);
  // null zolang niemand iets koos: dan geldt de voorkeuze hieronder, ook als
  // de ledenlijst pas na het openen binnenkomt.
  const [keuze, setKeuze] = useState<string | null>(null);
  const ikKiesbaar = !!currentPerson && personOptions.some((o) => o.value === currentPerson.id);
  const wie = metEigenaar ? (keuze ?? (ikKiesbaar ? currentPerson.id : '')) : '';

  const opslaan = async () => {
    const title = titel.trim();
    if (!title || create.isPending) return;
    try {
      const taak = await create.mutateAsync({
        title,
        issue_id: issue.id,
        ...(status !== TaskStatus.OPEN ? { status } : {}),
        ...(wie ? { assignee_id: wie } : {}),
      });
      onAangemaakt?.(taak);
      onClose();
    } catch {
      // de melding is al getoond; het venster blijft open
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Taak toevoegen"
      size="sm"
      closeable={!create.isPending}
      footer={
        <>
          <NlddButton variant="secondary" onClick={onClose} text="Annuleren" disabled={create.isPending} />
          <NlddButton onClick={() => void opslaan()} loading={create.isPending} disabled={!titel.trim()} text="Toevoegen" />
        </>
      }
    >
      <nldd-container gap="16">
        <nldd-container gap="4">
          <nldd-text size="sm" color="secondary">Bij: {issue.title}</nldd-text>
          <nldd-text size="sm" color="secondary">In: {kolomNaam ?? TASK_STATUS_LABELS[status]}</nldd-text>
        </nldd-container>
        <Input
          label="Taak"
          type="text"
          value={titel}
          onChange={(e) => setTitel(e.target.value)}
          placeholder="Wat moet er gebeuren?"
          required
          onKeyDown={(e) => {
            if (e.key === 'Enter') void opslaan();
          }}
        />
        {/* Opnieuw tekenen zodra de leden binnen zijn: de dropdown ververst
            zijn label niet als alleen de opties veranderen. */}
        {metEigenaar && (
          <Select
            key={personOptions.length}
            compact
            label="Eigenaar"
            width="240px"
            options={personOptions}
            value={wie}
            onChange={(e) => setKeuze(e.target.value)}
          />
        )}
      </nldd-container>
    </Modal>
  );
}
