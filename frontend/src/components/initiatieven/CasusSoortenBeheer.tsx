import { useState } from 'react';

import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { Input } from '@/components/common/Input';
import { Select } from '@/components/common/Select';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { TAG_KLEUR_OPTIES, leadColumnTagColor } from '@/components/leads/stageColors';
import {
  useCasusSoorten,
  useCreateCasusSoort,
  useDeleteCasusSoort,
  useReorderCasusSoorten,
  useUpdateCasusSoort,
} from '@/hooks/useCasusSoorten';
import type { CasusSoort } from '@/types';
import { CasusSoortDetailModal } from './CasusSoortDetailModal';

const KLEUREN = TAG_KLEUR_OPTIES.map((k) => ({ value: k.value, label: k.label }));

/**
 * Casussoorten beheren in de instellingen: de soorten die je als tags aan
 * een casus hangt. Elke wijziging wordt meteen opgeslagen; hernoemen werkt
 * meteen op alle casussen, verwijderen haalt de soort overal weg (met een
 * bevestiging die zegt op hoeveel casussen hij staat). Eigenaar-only, net
 * als de andere instellingen; de backend bewaakt dat ook.
 */
export function CasusSoortenBeheer({ initiatiefId }: { initiatiefId: string }) {
  const { data: soorten = [], isLoading } = useCasusSoorten(initiatiefId);
  const create = useCreateCasusSoort();
  const reorder = useReorderCasusSoorten();
  const [naam, setNaam] = useState('');
  const [kleur, setKleur] = useState('neutral');
  const [uitleg, setUitleg] = useState('');
  const [weg, setWeg] = useState<CasusSoort | null>(null);
  // De soort waarvan het detailvenster open is.
  const [detailId, setDetailId] = useState<string | null>(null);
  const del = useDeleteCasusSoort();

  const voegToe = async () => {
    const n = naam.trim();
    if (!n) return;
    try {
      await create.mutateAsync({ initiatiefId, naam: n, kleur, uitleg: uitleg.trim() || null });
      setNaam('');
      setUitleg('');
    } catch {
      // toast is al getoond (bijvoorbeeld: bestaat al)
    }
  };
  const verplaats = (i: number, richting: -1 | 1) => {
    const j = i + richting;
    if (j < 0 || j >= soorten.length) return;
    const ids = soorten.map((s) => s.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    reorder.mutate({ initiatiefId, soortIds: ids });
  };

  return (
    <nldd-container gap="12">
      <nldd-text size="sm" color="secondary">
        Soorten casus die je als labels aan een casus hangt, bij het starten of later bij de casusgegevens.
        De uitleg staat bij het kiezen en als tooltip op het label. Een wijziging werkt meteen op alle
        casussen.
      </nldd-text>
      {isLoading ? (
        <nldd-text size="sm" color="secondary">Laden...</nldd-text>
      ) : soorten.length === 0 ? (
        <nldd-text size="sm" color="secondary">Nog geen soorten.</nldd-text>
      ) : (
        <nldd-container gap="16">
          {soorten.map((s, i) => (
            <SoortRegel
              key={s.id}
              soort={s}
              initiatiefId={initiatiefId}
              eerste={i === 0}
              laatste={i === soorten.length - 1}
              onOmhoog={() => verplaats(i, -1)}
              onOmlaag={() => verplaats(i, 1)}
              onVerwijder={() => setWeg(s)}
              onOpen={() => setDetailId(s.id)}
            />
          ))}
        </nldd-container>
      )}
      <nldd-container layout="row" gap="8" vertical-alignment="center">
        <nldd-container className="row-fill">
          <Input
            type="text"
            value={naam}
            aria-label="Nieuwe soort"
            maxLength={100}
            placeholder="Nieuwe soort, bijvoorbeeld: wetgeving"
            onChange={(e) => setNaam(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void voegToe();
            }}
          />
        </nldd-container>
        <div style={{ width: '160px', flexShrink: 0 }}>
          <Select size="sm" aria-label="Kleur van de nieuwe soort" options={KLEUREN} value={kleur} onChange={(e) => setKleur(e.target.value)} />
        </div>
        <NlddButton variant="secondary" size="sm" startIcon="plus" onClick={() => void voegToe()} loading={create.isPending} disabled={!naam.trim()} text="Toevoegen" />
      </nldd-container>
      <Input
        type="text"
        value={uitleg}
        aria-label="Uitleg bij de nieuwe soort"
        maxLength={500}
        placeholder="Uitleg, bijvoorbeeld: we proberen iets nieuws uit om ervan te leren"
        onChange={(e) => setUitleg(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void voegToe();
        }}
      />
      <CasusSoortDetailModal
        soort={soorten.find((s) => s.id === detailId) ?? null}
        initiatiefId={initiatiefId}
        onClose={() => setDetailId(null)}
      />
      <ConfirmDialog
        open={!!weg}
        onClose={() => setWeg(null)}
        onConfirm={async () => {
          if (!weg) return;
          try {
            await del.mutateAsync({ initiatiefId, soortId: weg.id });
            setWeg(null);
          } catch {
            // toast is al getoond
          }
        }}
        title="Soort verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={del.isPending}
      >
        {weg
          ? `"${weg.naam}" verdwijnt uit de instellingen${
              weg.casus_count > 0 ? ` en van ${weg.casus_count} ${weg.casus_count === 1 ? 'casus' : 'casussen'}` : ''
            }.`
          : ''}
      </ConfirmDialog>
    </nldd-container>
  );
}

interface RegelProps {
  soort: CasusSoort;
  initiatiefId: string;
  eerste: boolean;
  laatste: boolean;
  onOmhoog: () => void;
  onOmlaag: () => void;
  onVerwijder: () => void;
  onOpen: () => void;
}

/** Eén soort: naam (opslaan bij Enter of verlaten), kleur, volgorde, weg. */
function SoortRegel({ soort, initiatiefId, eerste, laatste, onOmhoog, onOmlaag, onVerwijder, onOpen }: RegelProps) {
  const update = useUpdateCasusSoort();
  const [naam, setNaam] = useState(soort.naam);
  const [uitleg, setUitleg] = useState(soort.uitleg ?? '');
  const opslaan = (data: { naam?: string; kleur?: string; uitleg?: string | null }) =>
    update.mutate(
      { initiatiefId, soortId: soort.id, data },
      // Bij een fout (bijvoorbeeld dubbele naam) terug naar wat er stond.
      {
        onError: () => {
          setNaam(soort.naam);
          setUitleg(soort.uitleg ?? '');
        },
      },
    );
  const uitlegOpslaan = () => {
    const u = uitleg.trim();
    if (u !== (soort.uitleg ?? '')) opslaan({ uitleg: u || null });
  };
  const naamOpslaan = () => {
    const n = naam.trim();
    if (!n) return setNaam(soort.naam);
    if (n !== soort.naam) opslaan({ naam: n });
  };

  return (
    <nldd-container gap="4">
    <nldd-container layout="row" gap="8" vertical-alignment="center">
      <nldd-container className="row-fill">
        <Input
          type="text"
          value={naam}
          aria-label={`Naam van ${soort.naam}`}
          maxLength={100}
          onChange={(e) => setNaam(e.target.value)}
          onBlur={naamOpslaan}
          onKeyDown={(e) => {
            if (e.key === 'Enter') naamOpslaan();
          }}
        />
      </nldd-container>
      <div style={{ width: '160px', flexShrink: 0 }}>
        <Select
          size="sm"
          aria-label={`Kleur van ${soort.naam}`}
          options={KLEUREN}
          value={soort.kleur}
          onChange={(e) => opslaan({ kleur: e.target.value })}
        />
      </div>
      {/* Zo ziet de tag eruit op een casus. Vaste breedte, zodat de regels
          onder elkaar blijven staan; een lange naam wordt afgekapt. */}
      <div style={{ width: '140px', flexShrink: 0, overflow: 'hidden', whiteSpace: 'nowrap' }}>
        <nldd-tag text={soort.naam} color={leadColumnTagColor(soort.kleur)} size="sm" />
      </div>
      <nldd-text size="xs" color="secondary" style={{ width: '80px', flexShrink: 0, textAlign: 'right', whiteSpace: 'nowrap' }}>
        {soort.casus_count === 1 ? '1 casus' : `${soort.casus_count} casussen`}
      </nldd-text>
      <NlddIconButton icon="arrow-up" accessibleLabel={`${soort.naam} omhoog`} variant="neutral-transparent" size="sm" disabled={eerste} onClick={onOmhoog} />
      <NlddIconButton icon="arrow-down" accessibleLabel={`${soort.naam} omlaag`} variant="neutral-transparent" size="sm" disabled={laatste} onClick={onOmlaag} />
      <NlddIconButton icon="trash" accessibleLabel={`${soort.naam} verwijderen`} variant="neutral-transparent" size="sm" onClick={onVerwijder} />
      {/* In detail: hoe ver we zo'n casus brengen, met punten. */}
      <NlddIconButton icon="ellipsis" accessibleLabel={`${soort.naam} in detail`} variant="neutral-transparent" size="sm" onClick={onOpen} />
    </nldd-container>
    {/* De uitleg: opslaan bij Enter of verlaten, leeg wist hem. */}
    <Input
      type="text"
      value={uitleg}
      aria-label={`Uitleg bij ${soort.naam}`}
      maxLength={500}
      placeholder="Uitleg (optioneel): wat betekent deze soort?"
      onChange={(e) => setUitleg(e.target.value)}
      onBlur={uitlegOpslaan}
      onKeyDown={(e) => {
        if (e.key === 'Enter') uitlegOpslaan();
      }}
    />
    </nldd-container>
  );
}
