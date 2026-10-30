import { useMemo, useState } from 'react';

import { Input } from '@/components/common/Input';
import { Modal } from '@/components/common/Modal';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { Select } from '@/components/common/Select';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useCasussen } from '@/hooks/useCasussen';
import { useInitiatiefPersonOptions } from '@/hooks/useInitiatiefPersonOptions';
import { useCreateIssue } from '@/hooks/useIssues';
import { richTextToPlain } from '@/utils/richtext';
import { OnderzoeksvraagVinkje } from './OnderzoeksvraagVinkje';

interface Props {
  open: boolean;
  onClose: () => void;
  initiatiefId: string;
  /** Voorgekozen casus, bijvoorbeeld die van het filter in de backlog. */
  casusId?: string;
}

/**
 * Een onderzoeksvraag aanmaken vanuit de backlog, zonder dat er al taken
 * onder hoeven. Onderzoeksvragen zijn leidend: wat je hier aanmaakt is er
 * een, tenzij je "Dit is geen onderzoeksvraag" aanvinkt. Het hoort altijd
 * bij een casus, dus die kies je hier; met maar één casus in het initiatief
 * staat die al klaar.
 */
export function IssueAanmakenModal({ open, ...props }: Props) {
  if (!open) return null;
  // Elke keer een leeg formulier.
  return <Formulier {...props} />;
}

function Formulier({ onClose, initiatiefId, casusId: voorgekozen }: Omit<Props, 'open'>) {
  const create = useCreateIssue();
  const { data: casussen, isSuccess: casussenGeladen } = useCasussen(initiatiefId);
  const personOptions = useInitiatiefPersonOptions(null, initiatiefId);

  const [titel, setTitel] = useState('');
  const [isVraag, setIsVraag] = useState(true);
  const [casusKeuze, setCasusKeuze] = useState(voorgekozen ?? '');
  const [wie, setWie] = useState('');
  const [toelichting, setToelichting] = useState('');

  const casusOptions = useMemo(
    () =>
      (casussen ?? [])
        .filter((c) => c.initiatief_id === initiatiefId)
        .map((c) => ({ value: c.id, label: c.title }))
        .sort((a, b) => a.label.localeCompare(b.label, 'nl')),
    [casussen, initiatiefId],
  );
  const casusId = casusKeuze || (casusOptions.length === 1 ? casusOptions[0].value : '');

  const opslaan = async () => {
    const t = titel.trim();
    if (!t || !casusId) return;
    try {
      await create.mutateAsync({
        casusId,
        data: {
          title: t,
          is_onderzoeksvraag: isVraag,
          assignee_id: wie || null,
          toelichting: richTextToPlain(toelichting).trim() ? toelichting : null,
        },
      });
      onClose();
    } catch {
      // de melding is al getoond; het venster blijft open
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Onderzoeksvraag toevoegen"
      size="md"
      closeable={!create.isPending}
      footer={
        <>
          <NlddButton variant="secondary" onClick={onClose} text="Annuleren" disabled={create.isPending} />
          <NlddButton onClick={() => void opslaan()} loading={create.isPending} disabled={!titel.trim() || !casusId} text="Toevoegen" />
        </>
      }
    >
      <nldd-container gap="16">
        <Input
          label={isVraag ? 'Onderzoeksvraag' : 'Titel'}
          type="text"
          value={titel}
          onChange={(e) => setTitel(e.target.value)}
          placeholder={isVraag ? 'Welke vraag beantwoorden we?' : 'Wat moet er gebeuren?'}
          required
        />
        {/* De uitzondering, direct onder de vraag zelf. */}
        <OnderzoeksvraagVinkje checked={isVraag} onChange={setIsVraag} />
        {/* Opnieuw tekenen zodra de casussen binnen zijn: de dropdown ververst
            zijn label niet als alleen de opties veranderen. */}
        <Select
          key={casussenGeladen ? 'geladen' : 'laden'}
          compact
          required
          label="Casus"
          placeholder={casussenGeladen ? 'Kies een casus' : 'Laden...'}
          options={casusOptions}
          value={casusId}
          disabled={!casussenGeladen}
          onChange={(e) => setCasusKeuze(e.target.value)}
        />
        <Select compact label="Eigenaar" width="240px" options={personOptions} value={wie} onChange={(e) => setWie(e.target.value)} />
        <RichTextFormField hideOptional label="Toelichting" value={toelichting} onChange={setToelichting} rows={3} placeholder="Waarom deze vraag, wat is de context?" />
      </nldd-container>
    </Modal>
  );
}
