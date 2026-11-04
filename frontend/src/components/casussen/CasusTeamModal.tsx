import { useEffect, useState } from 'react';

import { Modal } from '@/components/common/Modal';
import { Select } from '@/components/common/Select';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useInitiatiefPersonen } from '@/hooks/useInitiatieven';
import { useLead } from '@/hooks/useLeads';
import { usePeople } from '@/hooks/usePeople';
import { useAddCasusTeamlid } from '@/hooks/useCasussen';
import { CASUSTEAM_ROL_LABELS } from '@/types';
import type { CasusDetail } from '@/types';

const ROL_OPTIONS: SelectOption[] = Object.entries(CASUSTEAM_ROL_LABELS).map(([value, label]) => ({ value, label }));

interface Props {
  casus: CasusDetail | null;
  onClose: () => void;
}

/**
 * Teamlid toevoegen: alleen wie het initiatief van de casus kan zien. De
 * contacten van de lead staan bovenaan; wie daarvan nog geen lid is, staat
 * eronder genoemd, want die moet eerst bij het initiatief.
 */
export function CasusTeamModal({ casus, onClose }: Props) {
  const add = useAddCasusTeamlid();
  const { data: initiatiefPersonen } = useInitiatiefPersonen(casus?.initiatief_id ?? undefined);
  const { data: allePersonen = [] } = usePeople();
  const { data: lead } = useLead(casus?.lead_id ?? null);
  const kandidaten = casus?.initiatief_id ? (initiatiefPersonen ?? []) : allePersonen;
  const opTeam = (personId: string) => !!casus?.team.some((t) => t.person_id === personId);
  const contactIds = new Set((lead?.contacts ?? []).map((c) => c.person_id));
  const kiesbaar = new Set(kandidaten.map((p) => p.id));
  // Per persoon één keer, ook als die meer rollen op de lead heeft.
  const contactenZonderLidmaatschap = [
    ...new Map(
      (lead?.contacts ?? [])
        .filter((c) => !kiesbaar.has(c.person_id) && !opTeam(c.person_id))
        .map((c) => [c.person_id, c.person_naam]),
    ).values(),
  ];

  const [personId, setPersonId] = useState('');
  const [rol, setRol] = useState<'trekker' | 'teamlid'>('teamlid');

  useEffect(() => {
    setPersonId('');
    setRol('teamlid');
  }, [casus?.id]);

  // Contacten van de lead eerst; verder de volgorde van het initiatief.
  const options: SelectOption[] = kandidaten
    .filter((p) => !opTeam(p.id))
    .sort((a, b) => Number(contactIds.has(b.id)) - Number(contactIds.has(a.id)))
    .map((p) => ({
      value: p.id,
      label: p.naam,
      description: contactIds.has(p.id)
        ? ['Contact op de lead', p.functie].filter(Boolean).join(' · ')
        : (p.functie ?? undefined),
    }));

  const submit = async () => {
    if (!casus || !personId) return;
    try {
      await add.mutateAsync({ casusId: casus.id, personId, rol });
      onClose();
    } catch {
      // toast is al getoond
    }
  };

  return (
    <Modal
      open={!!casus}
      onClose={onClose}
      title="Teamlid toevoegen"
      size="md"
      closeable={!add.isPending}
      footer={
        <>
          <NlddButton variant="secondary" onClick={onClose} text="Annuleren" />
          <NlddButton onClick={submit} loading={add.isPending} disabled={!personId} text="Toevoegen" />
        </>
      }
    >
      <nldd-container gap="16">
        {casus?.initiatief_id && (
          <nldd-text size="sm" color="secondary">
            Alleen wie {casus.initiatief?.naam ?? 'het initiatief'} kan zien is kiesbaar. Iemand
            anders eerst toevoegen aan het initiatief.
          </nldd-text>
        )}
        <CreatableSelect label="Persoon" value={personId} onChange={setPersonId} options={options} placeholder="Zoek een persoon..." required />
        {casus?.initiatief_id && contactenZonderLidmaatschap.length > 0 && (
          <nldd-text size="sm" color="secondary">
            Contact op de lead, nog geen lid: {contactenZonderLidmaatschap.join(', ')}. Voeg{' '}
            {contactenZonderLidmaatschap.length === 1 ? 'deze persoon' : 'ze'} eerst toe aan het initiatief
            (tab Mensen), dan {contactenZonderLidmaatschap.length === 1 ? 'is die' : 'zijn ze'} hier te kiezen.
          </nldd-text>
        )}
        <Select label="Rol" options={ROL_OPTIONS} value={rol} onChange={(e) => setRol(e.target.value as 'trekker' | 'teamlid')} />
      </nldd-container>
    </Modal>
  );
}
