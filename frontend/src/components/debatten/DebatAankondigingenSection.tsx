import { useCallback, useMemo, useRef, useState } from 'react';
import { Badge } from '@/components/common/Badge';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Icon } from '@/components/nldd/Icon';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { useToast } from '@/contexts/ToastContext';
import { useDebounce } from '@/hooks/useDebounce';
import {
  useDebatAankondigingen,
  useDebatAgenda,
  useKondigDebatAan,
  useVerwijderDebatAankondiging,
} from '@/hooks/useDebatten';
import type { AankomendDebat, DebatAankondiging } from '@/types/debat';
import {
  ZOEK_MIN,
  aankondigMelding,
  aankondigingBadge,
  formatAankondigingRegel,
  zoekDebatten,
} from './aankondigingen';

/** `nldd-search-field` with its `input` event bridged to React. */
function AgendaSearchField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));
  return (
    <nldd-search-field
      ref={ref}
      value={value}
      placeholder="Zoek een komende vergadering op onderwerp of commissie..."
      accessible-label="Zoek een komende vergadering om aan te kondigen"
    />
  );
}

function AgendaLink({ url, onderwerp }: { url: string | null; onderwerp: string }) {
  if (!url) return null;
  return (
    <nldd-cell horizontal-alignment="right" hide-below="md">
      <nldd-link
        href={url}
        target="_blank"
        text="Agenda"
        accessible-label={`Agenda van ${onderwerp}`}
      />
    </nldd-cell>
  );
}

function AankondigingRow({
  debat,
  busy,
  onVerwijder,
}: {
  debat: DebatAankondiging;
  busy: boolean;
  /** Absent for someone who may only look. */
  onVerwijder?: (debat: DebatAankondiging) => void;
}) {
  const badge = aankondigingBadge(debat);
  return (
    <nldd-list-item>
      <nldd-text-cell text={debat.onderwerp} supporting-text={formatAankondigingRegel(debat)} />
      {badge && (
        <nldd-cell horizontal-alignment="right">
          <Badge color={badge.color}>{badge.label}</Badge>
        </nldd-cell>
      )}
      {debat.agenda_url && <nldd-spacer-cell size="16" hide-below="md" />}
      <AgendaLink url={debat.agenda_url} onderwerp={debat.onderwerp} />
      {onVerwijder && (
        <>
          <nldd-spacer-cell size="8" />
          <nldd-cell horizontal-alignment="right">
            <NlddIconButton
              icon="trash"
              accessibleLabel={`${debat.onderwerp} van de lijst halen`}
              variant="neutral-transparent"
              size="sm"
              disabled={busy}
              onClick={() => onVerwijder(debat)}
            />
          </nldd-cell>
        </>
      )}
    </nldd-list-item>
  );
}

function ResultaatRow({
  debat,
  aangekondigd,
  pending,
  busy,
  onKondigAan,
}: {
  debat: AankomendDebat;
  aangekondigd: boolean;
  pending: boolean;
  busy: boolean;
  onKondigAan: (debat: AankomendDebat) => void;
}) {
  return (
    <nldd-list-item>
      <nldd-text-cell text={debat.onderwerp} supporting-text={formatAankondigingRegel(debat)} />
      <AgendaLink url={debat.agenda_url} onderwerp={debat.onderwerp} />
      <nldd-spacer-cell size="16" />
      <nldd-cell horizontal-alignment="right">
        {aangekondigd ? (
          <Badge color="coolgray">Staat op de lijst</Badge>
        ) : (
          <NlddButton
            variant="secondary"
            size="sm"
            startIcon="megaphone"
            text="Aankondigen"
            compactBelowSm
            accessibleLabel={`${debat.onderwerp} aankondigen`}
            loading={pending}
            disabled={busy}
            onClick={() => onKondigAan(debat)}
          />
        )}
      </nldd-cell>
    </nldd-list-item>
  );
}

/**
 * Debates announced for this initiatief, and announcing another one.
 *
 * Announcing posts one message in the channels of the initiatief that have
 * "Kamerstuk-alerts" on,
 * and a reminder on the morning of the debate. The search reads the agenda
 * of the Kamer only once someone types: most visits to this tab are not
 * about a debate.
 *
 * A viewer sees the list and nothing to press: an announcement makes the bot
 * post in the channels, and the backend refuses that below contributor.
 */
export function DebatAankondigingenSection({
  initiatiefId,
  canEdit,
}: {
  initiatiefId: string;
  canEdit: boolean;
}) {
  const aankondigingen = useDebatAankondigingen(initiatiefId);
  const kondigAan = useKondigDebatAan(initiatiefId);
  const verwijder = useVerwijderDebatAankondiging(initiatiefId);
  const { showSuccess } = useToast();
  const [search, setSearch] = useState('');
  const debounced = useDebounce(search, 200);
  const zoekt = canEdit && debounced.trim().length >= ZOEK_MIN;
  const agenda = useDebatAgenda(zoekt);

  const lijst = useMemo(() => aankondigingen.data ?? [], [aankondigingen.data]);
  const { resultaten, meer } = useMemo(
    () => zoekDebatten(agenda.data?.debatten ?? [], debounced, lijst),
    [agenda.data, debounced, lijst],
  );

  const busy = kondigAan.isPending || verwijder.isPending;

  const handleKondigAan = useCallback(
    (debat: AankomendDebat) => {
      kondigAan.mutate(
        { activiteitId: debat.activiteit_id },
        { onSuccess: (result) => showSuccess(aankondigMelding(result.gepost_in)) },
      );
    },
    [kondigAan, showSuccess],
  );

  const handleVerwijder = useCallback(
    (debat: DebatAankondiging) => {
      verwijder.mutate(
        { aankondigingId: debat.id },
        {
          onSuccess: () =>
            showSuccess('Het debat is van de lijst. Wat al gepost is blijft staan.'),
        },
      );
    },
    [verwijder, showSuccess],
  );

  return (
    <nldd-card>
      <nldd-container gap="12" padding="16">
        <nldd-container layout="row" gap="6" vertical-alignment="center">
          <Icon name="megaphone" size="sm" />
          <nldd-text size="xs" weight="bold" color="secondary">
            Debatten
          </nldd-text>
        </nldd-container>
        <nldd-text size="sm" color="secondary">
          {canEdit
            ? 'Kondig een debat aan in de kanalen van dit initiatief waar Kamerstuk-alerts aan staat. Op de ochtend van het debat volgt daar een herinnering, of het bericht dat het niet doorgaat.'
            : 'Debatten die zijn aangekondigd in de kanalen van dit initiatief waar Kamerstuk-alerts aan staat. Op de ochtend van het debat volgt daar een herinnering, of het bericht dat het niet doorgaat.'}
        </nldd-text>

        {aankondigingen.isLoading && (
          <nldd-container padding-block="24">
            <LoadingSpinner />
          </nldd-container>
        )}
        {aankondigingen.isError && (
          <nldd-inline-dialog
            variant="alert"
            size="md"
            text="Kon de aangekondigde debatten niet ophalen."
          />
        )}
        {lijst.length > 0 && (
          <nldd-list appearance="box-tinted" dividers="always" accessible-label="Aangekondigde debatten">
            {lijst.map((debat) => (
              <AankondigingRow
                key={debat.id}
                debat={debat}
                busy={busy}
                onVerwijder={canEdit ? handleVerwijder : undefined}
              />
            ))}
          </nldd-list>
        )}

        {!canEdit && !aankondigingen.isLoading && !aankondigingen.isError && lijst.length === 0 && (
          <nldd-inline-dialog text="Er is nog geen debat aangekondigd." />
        )}

        {canEdit && <AgendaSearchField value={search} onChange={setSearch} />}

        {zoekt && agenda.isLoading && <nldd-inline-dialog variant="loading" text="Agenda ophalen..." />}
        {zoekt && agenda.isError && (
          <nldd-inline-dialog
            variant="alert"
            size="md"
            text="De agenda van de Tweede Kamer is nu niet op te halen."
            supporting-text="Probeer het over een paar minuten opnieuw."
          />
        )}
        {zoekt && agenda.data && resultaten.length === 0 && (
          <nldd-inline-dialog
            icon="question-mark-circle"
            text="Geen komende vergadering past bij deze zoekterm."
            supporting-text="De agenda loopt drie weken vooruit."
          />
        )}
        {resultaten.length > 0 && (
          <nldd-list appearance="box-tinted" dividers="always" accessible-label="Gevonden vergaderingen">
            {resultaten.map(({ debat, aangekondigd }) => (
              <ResultaatRow
                key={debat.activiteit_id}
                debat={debat}
                aangekondigd={aangekondigd}
                pending={
                  kondigAan.isPending && kondigAan.variables?.activiteitId === debat.activiteit_id
                }
                busy={busy}
                onKondigAan={handleKondigAan}
              />
            ))}
          </nldd-list>
        )}
        {meer > 0 && (
          <nldd-text size="sm" color="secondary">
            En nog {meer} {meer === 1 ? 'vergadering' : 'vergaderingen'}. Zoek preciezer om ze te
            zien.
          </nldd-text>
        )}
      </nldd-container>
    </nldd-card>
  );
}
