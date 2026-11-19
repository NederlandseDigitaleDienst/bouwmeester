import { useRef, useState } from 'react';

import { getVerslagDownloadUrl } from '@/api/issues';
import { Badge } from '@/components/common/Badge';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import {
  useDeleteVerslag,
  useUploadVerslag,
  useVerslag,
  useVerslagNietOpenbaar,
  useVerslagOpenbaar,
} from '@/hooks/useIssues';
import type { VraagVoorBuiten } from '@/types';
import { bestandsgrootte } from '@/utils/bestandsgrootte';
import { formatDateLong } from '@/utils/dates';

/** Een verslag is een document; de backend controleert het ook. */
const ACCEPT = '.pdf,.doc,.docx,.odt';

/**
 * Het onderzoeksverslag bij een onderzoeksvraag, als bestand: uploaden,
 * vervangen, downloaden, weghalen. Eén verslag per vraag.
 *
 * Naar buiten gaat het pas na een akkoord ("Dit verslag verschijnt op de
 * publieke pagina. Akkoord?"), en dan nog alleen als de vraag zelf onder
 * Naar buiten is vrijgegeven. Een nieuw bestand vraagt een nieuw akkoord.
 */
export function OnderzoeksverslagBlok({ issue }: { issue: VraagVoorBuiten }) {
  const { data: verslag } = useVerslag(issue, issue.id);
  const upload = useUploadVerslag();
  const weghalen = useDeleteVerslag();
  const openbaar = useVerslagOpenbaar();
  const nietOpenbaar = useVerslagNietOpenbaar();
  const fileRef = useRef<HTMLInputElement>(null);
  const [vraagAkkoord, setVraagAkkoord] = useState(false);
  const [vraagWeg, setVraagWeg] = useState(false);

  if (!issue.is_onderzoeksvraag) return null;
  const ids = { plek: issue, issueId: issue.id };
  const vraagBuiten = !!issue.published_at;

  const kiesBestand = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) upload.mutate({ ...ids, file });
    e.target.value = '';
  };

  return (
    <nldd-container gap="8">
      <nldd-container layout="row" gap="8" vertical-alignment="center">
        <nldd-text size="md" weight="medium">
          Onderzoeksverslag
        </nldd-text>
        {verslag &&
          (verslag.openbaar_op ? <Badge color="groen">Openbaar</Badge> : <Badge color="coolgray">Binnen</Badge>)}
      </nldd-container>

      {verslag ? (
        <>
          <nldd-container layout="row" gap="8" vertical-alignment="center" width="full">
            <nldd-icon icon="paperclip" size="16" aria-hidden="true" />
            <nldd-text size="sm" className="truncate row-fill">
              {verslag.bestandsnaam}
            </nldd-text>
            <nldd-text size="xs" color="secondary">
              {bestandsgrootte(verslag.bestandsgrootte)}
            </nldd-text>
            <NlddIconButton
              icon="download"
              accessibleLabel={`${verslag.bestandsnaam} downloaden`}
              variant="neutral-transparent"
              size="sm"
              onClick={() => window.open(getVerslagDownloadUrl(issue, issue.id), '_blank')}
            />
            <NlddIconButton
              icon="trash"
              accessibleLabel={`${verslag.bestandsnaam} weghalen`}
              variant="neutral-transparent"
              size="sm"
              onClick={() => setVraagWeg(true)}
            />
          </nldd-container>
          <nldd-text size="xs" color="secondary">
            {`Geüpload ${formatDateLong(verslag.updated_at ?? verslag.created_at)}`}
            {verslag.uploaded_by_naam && ` door ${verslag.uploaded_by_naam}`}
            {verslag.openbaar_op &&
              `. Openbaar sinds ${formatDateLong(verslag.openbaar_op)}${verslag.openbaar_door_naam ? ` (${verslag.openbaar_door_naam})` : ''}`}
            .
          </nldd-text>
          {verslag.openbaar_op && !vraagBuiten && (
            <nldd-text size="xs" color="secondary">
              Op de publieke pagina staat het verslag pas als de vraag is vrijgegeven, onder Naar buiten.
            </nldd-text>
          )}
          <nldd-container layout="row" gap="8" horizontal-alignment="right">
            <NlddButton
              variant="neutral-transparent"
              size="sm"
              startIcon="upload"
              loading={upload.isPending}
              onClick={() => fileRef.current?.click()}
              text="Vervangen"
            />
            {verslag.openbaar_op ? (
              <NlddButton
                variant="secondary"
                size="sm"
                loading={nietOpenbaar.isPending}
                onClick={() => nietOpenbaar.mutate(ids)}
                text="Niet meer openbaar"
              />
            ) : (
              <NlddButton size="sm" onClick={() => setVraagAkkoord(true)} text="Openbaar maken" />
            )}
          </nldd-container>
        </>
      ) : (
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <nldd-text size="sm" color="secondary" className="row-fill">
            Nog geen verslag. Upload een PDF-, Word- of ODT-bestand.
          </nldd-text>
          <NlddButton
            variant="secondary"
            size="sm"
            startIcon="upload"
            loading={upload.isPending}
            onClick={() => fileRef.current?.click()}
            text="Uploaden"
          />
        </nldd-container>
      )}
      <input type="file" hidden accept={ACCEPT} ref={fileRef} onChange={kiesBestand} />

      <ConfirmDialog
        open={vraagAkkoord}
        onClose={() => setVraagAkkoord(false)}
        onConfirm={async () => {
          try {
            await openbaar.mutateAsync(ids);
            setVraagAkkoord(false);
          } catch {
            // de melding is al getoond
          }
        }}
        title="Verslag openbaar maken"
        confirmLabel="Akkoord"
        loading={openbaar.isPending}
      >
        {vraagBuiten
          ? 'Dit verslag verschijnt op de publieke pagina. Akkoord?'
          : 'Dit verslag verschijnt op de publieke pagina zodra de vraag is vrijgegeven onder Naar buiten. Akkoord?'}
      </ConfirmDialog>
      <ConfirmDialog
        open={vraagWeg}
        onClose={() => setVraagWeg(false)}
        onConfirm={async () => {
          try {
            await weghalen.mutateAsync(ids);
            setVraagWeg(false);
          } catch {
            // de melding is al getoond
          }
        }}
        title="Verslag weghalen"
        confirmLabel="Weghalen"
        variant="danger"
        loading={weghalen.isPending}
      >
        {`"${verslag?.bestandsnaam ?? ''}" wordt weggehaald, ook van de publieke pagina.`}
      </ConfirmDialog>
    </nldd-container>
  );
}
