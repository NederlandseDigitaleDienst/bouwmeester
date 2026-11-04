import { useState } from 'react';

import { Input } from '@/components/common/Input';
import { Modal } from '@/components/common/Modal';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { NlddButton } from '@/components/nldd/NlddButton';
import { leadColumnTagColor } from '@/components/leads/stageColors';
import { useUpdateCasusSoort } from '@/hooks/useCasusSoorten';
import type { CasusSoort } from '@/types';
import { richTextToPlain } from '@/utils/richtext';
import { EisenLijst } from './EisenLijst';

interface Props {
  soort: CasusSoort | null;
  initiatiefId: string;
  onClose: () => void;
}

/**
 * Eén casussoort in detail: wat de soort is, hoe ver we zo'n casus brengen,
 * en de eisen bij de start en aan het einde. Die eisen loopt het team na
 * als het een casus van deze soort start en als de casus in de laatste fase
 * van de funnel komt: per eis een vinkje en een opmerking, geen poort. Naam
 * en kleur staan op de regel in de instellingen.
 */
export function CasusSoortDetailModal({ soort, initiatiefId, onClose }: Props) {
  if (!soort) return null;
  // Opnieuw mounten per soort, zodat het formulier met diens waarden begint.
  return <Formulier key={soort.id} soort={soort} initiatiefId={initiatiefId} onClose={onClose} />;
}

function Formulier({ soort, initiatiefId, onClose }: { soort: CasusSoort; initiatiefId: string; onClose: () => void }) {
  const update = useUpdateCasusSoort();
  const [uitleg, setUitleg] = useState(soort.uitleg ?? '');
  const [hoeVer, setHoeVer] = useState(soort.hoe_ver ?? '');
  const [startEisen, setStartEisen] = useState<string[]>(soort.start_eisen ?? []);
  const [eindEisen, setEindEisen] = useState<string[]>(soort.eind_eisen ?? []);
  const schoon = (eisen: string[]) => eisen.map((e) => e.trim()).filter(Boolean);

  const opslaan = async () => {
    try {
      await update.mutateAsync({
        initiatiefId,
        soortId: soort.id,
        data: {
          uitleg: uitleg.trim() || null,
          hoe_ver: richTextToPlain(hoeVer).trim() ? hoeVer : null,
          start_eisen: schoon(startEisen),
          eind_eisen: schoon(eindEisen),
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
      title={soort.naam}
      entityLabel="Casussoort"
      size="lg"
      closeable={!update.isPending}
      footer={
        <>
          <NlddButton variant="secondary" onClick={onClose} text="Annuleren" disabled={update.isPending} />
          <NlddButton onClick={() => void opslaan()} loading={update.isPending} text="Opslaan" />
        </>
      }
    >
      <nldd-container gap="20">
        <div>
          <nldd-tag text={soort.naam} color={leadColumnTagColor(soort.kleur)} size="sm" />
        </div>
        {/* Kort: hij staat bij het kiezen van een soort en als tooltip op het label. */}
        <Input
          type="text"
          label="Omschrijving"
          value={uitleg}
          maxLength={500}
          placeholder="Wat voor casus is dit, bijvoorbeeld: we proberen iets nieuws uit om ervan te leren"
          onChange={(e) => setUitleg(e.target.value)}
        />
        <RichTextFormField
          hideOptional
          label="Hoe ver brengen we een casus van deze soort?"
          value={hoeVer}
          onChange={setHoeVer}
          rows={4}
          placeholder="Bijvoorbeeld: tot een werkend prototype bij één partner, nog niet in productie."
        />
        <nldd-container gap="8">
          <nldd-container gap="2">
            <nldd-text size="sm" weight="bold">Starteisen</nldd-text>
            <nldd-text size="xs" color="secondary">Wat ga je na als je een casus van deze soort start?</nldd-text>
          </nldd-container>
          <EisenLijst
            items={startEisen}
            onChange={setStartEisen}
            naam="Starteis"
            placeholder="Nieuwe starteis, bijvoorbeeld: er is een partner die meedoet"
            leeg="Geen starteisen. Voeg er hieronder een toe."
            nieuwLabel="Nieuwe starteis"
          />
        </nldd-container>
        <nldd-container gap="8">
          <nldd-container gap="2">
            <nldd-text size="sm" weight="bold">Eindeisen</nldd-text>
            <nldd-text size="xs" color="secondary">Wat is er af als een casus van deze soort zo ver is?</nldd-text>
          </nldd-container>
          <EisenLijst
            items={eindEisen}
            onChange={setEindEisen}
            naam="Eindeis"
            placeholder="Nieuwe eindeis, bijvoorbeeld: demo gegeven aan de partner"
            leeg="Geen eindeisen. Voeg er hieronder een toe."
            nieuwLabel="Nieuwe eindeis"
          />
        </nldd-container>
      </nldd-container>
    </Modal>
  );
}
