import { useCallback, useRef, useState } from 'react';

import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { Input } from '@/components/common/Input';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { useNlddEvent } from '@/components/nldd/events';
import { leadColumnTagColor } from '@/components/leads/stageColors';
import {
  useCasusSoorten,
  useCreateCasusSoort,
  useDeleteCasusSoort,
  useReorderCasusSoorten,
} from '@/hooks/useCasusSoorten';
import type { CasusSoort } from '@/types';
import { CasusSoortDetailModal } from './CasusSoortDetailModal';

const aantal = (n: number, een: string, meer: string) => `${n} ${n === 1 ? een : meer}`;

/**
 * Casussoorten beheren in de instellingen. De lijst toont per soort het
 * label, de omschrijving en hoeveel voorwaarden en deliverables hij heeft; klik
 * een soort aan en je regelt alles in een eigen scherm: naam, kleur,
 * omschrijving, de voorwaarden om te starten en de deliverables. Een nieuwe soort
 * begint met alleen een naam en opent meteen dat scherm. Eigenaar-only, net
 * als de andere instellingen; de backend bewaakt dat ook.
 */
export function CasusSoortenBeheer({ initiatiefId }: { initiatiefId: string }) {
  const { data: soorten = [], isLoading } = useCasusSoorten(initiatiefId);
  const create = useCreateCasusSoort();
  const reorder = useReorderCasusSoorten();
  const del = useDeleteCasusSoort();
  const [naam, setNaam] = useState('');
  const [weg, setWeg] = useState<CasusSoort | null>(null);
  // De soort waarvan het scherm open is.
  const [detailId, setDetailId] = useState<string | null>(null);

  const voegToe = async () => {
    const n = naam.trim();
    if (!n) return;
    try {
      const nieuw = await create.mutateAsync({ initiatiefId, naam: n, kleur: 'neutral', uitleg: null });
      setNaam('');
      setDetailId(nieuw.id);
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
        Soorten casus die je als labels aan een casus hangt. Open een soort om de voorwaarden om te starten en de
        deliverables te regelen. Een wijziging werkt meteen op alle casussen.
      </nldd-text>
      {isLoading ? (
        <nldd-text size="sm" color="secondary">Laden...</nldd-text>
      ) : soorten.length === 0 ? (
        <nldd-text size="sm" color="secondary">Nog geen soorten.</nldd-text>
      ) : (
        <nldd-container gap="8">
          {soorten.map((s, i) => (
            <nldd-container key={s.id} layout="row" gap="4" vertical-alignment="center">
              <nldd-container className="row-fill">
                <SoortKaart soort={s} onOpen={() => setDetailId(s.id)} />
              </nldd-container>
              <NlddIconButton icon="arrow-up" accessibleLabel={`${s.naam} omhoog`} variant="neutral-transparent" size="sm" disabled={i === 0} onClick={() => verplaats(i, -1)} />
              <NlddIconButton icon="arrow-down" accessibleLabel={`${s.naam} omlaag`} variant="neutral-transparent" size="sm" disabled={i === soorten.length - 1} onClick={() => verplaats(i, 1)} />
            </nldd-container>
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
        <NlddButton variant="secondary" size="sm" startIcon="plus" onClick={() => void voegToe()} loading={create.isPending} disabled={!naam.trim()} text="Toevoegen" />
      </nldd-container>
      <CasusSoortDetailModal
        soort={soorten.find((s) => s.id === detailId) ?? null}
        initiatiefId={initiatiefId}
        onClose={() => setDetailId(null)}
        onVerwijder={(s) => setWeg(s)}
      />
      <ConfirmDialog
        open={!!weg}
        onClose={() => setWeg(null)}
        onConfirm={async () => {
          if (!weg) return;
          try {
            await del.mutateAsync({ initiatiefId, soortId: weg.id });
            setWeg(null);
            setDetailId(null);
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
              weg.casus_count > 0 ? ` en van ${aantal(weg.casus_count, 'casus', 'casussen')}` : ''
            }.`
          : ''}
      </ConfirmDialog>
    </nldd-container>
  );
}

/** Eén soort in de lijst: klik hem aan voor het scherm met alles erover. */
function SoortKaart({ soort, onOpen }: { soort: CasusSoort; onOpen: () => void }) {
  const ref = useRef<HTMLElement>(null);
  const handleClick = useCallback(() => onOpen(), [onOpen]);
  useNlddEvent(ref, 'click', handleClick);
  const start = soort.start_eisen?.length ?? 0;
  const deliverables = soort.eind_eisen?.length ?? 0;

  return (
    <nldd-card ref={ref} button accessible-label={`${soort.naam} openen`}>
      <nldd-container gap="4" padding="12">
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <nldd-container className="row-fill">
            <div>
              <nldd-tag text={soort.naam} color={leadColumnTagColor(soort.kleur)} size="sm" />
            </div>
          </nldd-container>
          <nldd-text size="xs" color="secondary" style={{ whiteSpace: 'nowrap' }}>
            {aantal(start, 'voorwaarde om te starten', 'voorwaarden om te starten')} · {aantal(deliverables, 'deliverable', 'deliverables')} ·{' '}
            {aantal(soort.casus_count, 'casus', 'casussen')}
          </nldd-text>
        </nldd-container>
        <nldd-text size="sm" color="secondary" className="line-clamp-2">
          {soort.uitleg || 'Nog geen omschrijving.'}
        </nldd-text>
      </nldd-container>
    </nldd-card>
  );
}
