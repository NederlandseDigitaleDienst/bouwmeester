import { useEffect, useState } from 'react';

import { Modal } from '@/components/common/Modal';
import { Select } from '@/components/common/Select';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useInitiatiefPersonen } from '@/hooks/useInitiatieven';
import { usePeople } from '@/hooks/usePeople';
import { useAddCasusTeamlid } from '@/hooks/useCasussen';
import { CASUSTEAM_ROL_LABELS } from '@/types';
import type { CasusDetail } from '@/types';

const ROL_OPTIONS: SelectOption[] = Object.entries(CASUSTEAM_ROL_LABELS).map(([value, label]) => ({ value, label }));

interface Props {
  casus: CasusDetail | null;
  onClose: () => void;
}

/** Teamlid toevoegen: alleen wie het initiatief van de casus kan zien. */
export function CasusTeamModal({ casus, onClose }: Props) {
  const add = useAddCasusTeamlid();
  const { data: initiatiefPersonen } = useInitiatiefPersonen(casus?.initiatief_id ?? undefined);
  const { data: allePersonen = [] } = usePeople();
  const kandidaten = casus?.initiatief_id ? (initiatiefPersonen ?? []) : allePersonen;

  const [personId, setPersonId] = useState('');
  const [rol, setRol] = useState<'trekker' | 'teamlid'>('teamlid');

  useEffect(() => {
    setPersonId('');
    setRol('teamlid');
  }, [casus?.id]);

  const options: SelectOption[] = kandidaten
    .filter((p) => !casus?.team.some((t) => t.person_id === p.id))
    .map((p) => ({ value: p.id, label: p.naam, description: p.functie ?? undefined }));

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
        <Select label="Rol" options={ROL_OPTIONS} value={rol} onChange={(e) => setRol(e.target.value as 'trekker' | 'teamlid')} />
      </nldd-container>
    </Modal>
  );
}
