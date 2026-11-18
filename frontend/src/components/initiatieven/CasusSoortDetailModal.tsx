import { useState } from 'react';

import { Input } from '@/components/common/Input';
import { Modal } from '@/components/common/Modal';
import { Select } from '@/components/common/Select';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { NlddButton } from '@/components/nldd/NlddButton';
import { TAG_KLEUR_OPTIES, leadColumnTagColor } from '@/components/leads/stageColors';
import { useUpdateCasusSoort } from '@/hooks/useCasusSoorten';
import type { CasusSoort } from '@/types';
import { richTextToPlain } from '@/utils/richtext';
import { EisenLijst } from './EisenLijst';

const KLEUREN = TAG_KLEUR_OPTIES.map((k) => ({ value: k.value, label: k.label }));

interface Props {
  soort: CasusSoort | null;
  initiatiefId: string;
  onClose: () => void;
  /** Vraagt de aanroeper om de soort te verwijderen (met bevestiging). */
  onVerwijder?: (soort: CasusSoort) => void;
}

/**
 * Het scherm van één casussoort, geopend vanuit de instellingen: naam,
 * kleur, omschrijving, hoe ver we zo'n casus brengen, de voorwaarden om te starten
 * en de deliverables. De voorwaarden loopt het team na als het een casus van deze
 * soort start, de deliverables als de casus in de laatste fase van de funnel
 * komt (in de data heten die eind_eisen): per regel een vinkje en een
 * opmerking, geen poort.
 */
export function CasusSoortDetailModal({ soort, initiatiefId, onClose, onVerwijder }: Props) {
  if (!soort) return null;
  // Opnieuw mounten per soort, zodat het formulier met diens waarden begint.
  return <Formulier key={soort.id} soort={soort} initiatiefId={initiatiefId} onClose={onClose} onVerwijder={onVerwijder} />;
}

function Formulier({ soort, initiatiefId, onClose, onVerwijder }: { soort: CasusSoort } & Omit<Props, 'soort'>) {
  const update = useUpdateCasusSoort();
  const [naam, setNaam] = useState(soort.naam);
  const [kleur, setKleur] = useState(soort.kleur);
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
          naam: naam.trim(),
          kleur,
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
          <NlddButton onClick={() => void opslaan()} loading={update.isPending} disabled={!naam.trim()} text="Opslaan" />
        </>
      }
    >
      <nldd-container gap="20">
        <nldd-container layout="row" gap="8" vertical-alignment="bottom">
          <nldd-container className="row-fill">
            <Input type="text" label="Naam" required value={naam} maxLength={100} onChange={(e) => setNaam(e.target.value)} />
          </nldd-container>
          <div style={{ width: '160px', flexShrink: 0 }}>
            <Select label="Kleur" required options={KLEUREN} value={kleur} onChange={(e) => setKleur(e.target.value)} />
          </div>
          {/* Zo ziet het label eruit op een casus. */}
          <div style={{ paddingBottom: '8px' }}>
            <nldd-tag text={naam.trim() || soort.naam} color={leadColumnTagColor(kleur)} size="sm" />
          </div>
        </nldd-container>
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
            <nldd-text size="sm" weight="bold">Voorwaarden om te starten</nldd-text>
            <nldd-text size="xs" color="secondary">Wat ga je na als je een casus van deze soort start?</nldd-text>
          </nldd-container>
          <EisenLijst
            items={startEisen}
            onChange={setStartEisen}
            naam="Voorwaarde"
            placeholder="Nieuwe voorwaarde, bijvoorbeeld: er is een partner die meedoet"
            leeg="Nog geen voorwaarden om te starten. Voeg er hieronder een toe."
            nieuwLabel="Nieuwe voorwaarde"
          />
        </nldd-container>
        <nldd-container gap="8">
          <nldd-container gap="2">
            <nldd-text size="sm" weight="bold">Deliverables</nldd-text>
            <nldd-text size="xs" color="secondary">Wat levert een casus van deze soort op? Het team loopt ze na bij de laatste fase.</nldd-text>
          </nldd-container>
          <EisenLijst
            items={eindEisen}
            onChange={setEindEisen}
            naam="Deliverable"
            placeholder="Nieuwe deliverable, bijvoorbeeld: demo gegeven aan de partner"
            leeg="Nog geen deliverables. Voeg er hieronder een toe."
            nieuwLabel="Nieuwe deliverable"
          />
        </nldd-container>
        {/* Onderaan, los van de rest: verwijderen is niet terug te draaien. */}
        {onVerwijder && (
          <div>
            <NlddButton variant="neutral-transparent" size="sm" startIcon="trash" onClick={() => onVerwijder(soort)} text="Soort verwijderen" disabled={update.isPending} />
          </div>
        )}
      </nldd-container>
    </Modal>
  );
}
