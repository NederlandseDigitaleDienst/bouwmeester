import { Fragment, useCallback, useMemo, useRef, useState } from 'react';
import {
  useAankomendeDebatten,
  useGevolgdeDebatten,
  useHervatDebat,
  useStartDebat,
  useStopDebat,
} from '@/hooks/useDebatten';
import { useToast } from '@/contexts/ToastContext';
import { Badge } from '@/components/common/Badge';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Select } from '@/components/common/Select';
import { NlddButton } from '@/components/nldd/NlddButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import type { AankomendDebat, DebatKanaal, GevolgdDebat } from '@/types/debat';
import {
  KANAAL_LINK_TEKST,
  afloopBadge,
  filterDebatten,
  filterGevolgd,
  formatDebatRegel,
  formatGevolgdRegel,
  gevolgdeDebatten,
  kanaalActie,
  kanaalLinkLabel,
  kanStarten,
  bewaarGekozenTeam,
  kiesTeam,
  leesGekozenTeam,
  standBadge,
  verdeelDebatten,
  volgBadge,
  zichtbareKanalen,
  startMelding,
} from './debatten';

/** `nldd-search-field` with its `input` event bridged to React. */
function DebatSearchField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));
  return (
    <nldd-search-field
      ref={ref}
      value={value}
      placeholder="Zoek op onderwerp of commissie..."
      accessible-label="Zoek in debatten"
    />
  );
}

function KanaalLink({ kanaal, onderwerp }: { kanaal: DebatKanaal; onderwerp: string }) {
  const naam = `~${kanaal.channel_name}`;
  // A short fixed label: the subject on the row says which debate it is. The
  // channel name is in the accessible name and shows on hover.
  // Without the team's url name there is nothing to link to; the name alone
  // still tells which channel to look for.
  return kanaal.channel_url ? (
    <nldd-link
      href={kanaal.channel_url}
      target="_blank"
      text={KANAAL_LINK_TEKST}
      accessible-label={kanaalLinkLabel(onderwerp, kanaal)}
      title={naam}
    />
  ) : (
    <nldd-text size="sm" color="secondary">{naam}</nldd-text>
  );
}

interface DebatRowProps {
  debat: AankomendDebat;
  teamId: string | null;
  canStart: boolean;
  pending: boolean;
  busy: boolean;
  /** The sessie a stop or a resume is under way for, if any. */
  pendingSessieId: string | null;
  onStart: (debat: AankomendDebat) => void;
  onStop: (debat: AankomendDebat, kanaal: DebatKanaal) => void;
  onHervat: (kanaal: DebatKanaal) => void;
}

function DebatRow({
  debat,
  teamId,
  canStart,
  pending,
  busy,
  pendingSessieId,
  onStart,
  onStop,
  onHervat,
}: DebatRowProps) {
  const kanalen = zichtbareKanalen(debat, teamId);
  const badge = standBadge(debat);
  const volgt = volgBadge(debat, kanalen);
  return (
    <nldd-list-item>
      <nldd-text-cell text={debat.onderwerp} supporting-text={formatDebatRegel(debat, kanalen)} />
      {/* One cell per thing on the right, not a row container inside a cell:
          a cell is as wide as its content and a container as wide as its
          cell, so the two measure each other and both end at zero. Cells sit
          flush against each other, so the room between them is a spacer
          cell. */}
      {badge && (
        <nldd-cell horizontal-alignment="right">
          <Badge color={badge.color}>{badge.label}</Badge>
        </nldd-cell>
      )}
      {/* Where the row is narrow the second badge and the link to the agenda
          go: a row does not wrap, and the stop button already says the debate
          is followed. */}
      {volgt && (
        <>
          {badge && <nldd-spacer-cell size="8" hide-below="md" />}
          <nldd-cell horizontal-alignment="right" hide-below="md">
            <Badge color={volgt.color}>{volgt.label}</Badge>
          </nldd-cell>
        </>
      )}
      {debat.agenda_url && (
        <>
          {(badge || volgt) && <nldd-spacer-cell size="16" hide-below="md" />}
          <nldd-cell horizontal-alignment="right" hide-below="md">
            <nldd-link
              href={debat.agenda_url}
              target="_blank"
              text="Agenda"
              accessible-label={`Agenda van ${debat.onderwerp}`}
            />
          </nldd-cell>
        </>
      )}
      {kanalen.map((kanaal) => {
        const actie = kanaalActie(debat, kanaal);
        return (
          <Fragment key={kanaal.team_id}>
            <nldd-spacer-cell size="16" />
            <nldd-cell horizontal-alignment="right">
              <KanaalLink kanaal={kanaal} onderwerp={debat.onderwerp} />
            </nldd-cell>
            {actie && (
              <>
                <nldd-spacer-cell size="8" />
                <nldd-cell horizontal-alignment="right">
                  {actie === 'stoppen' ? (
                    <NlddButton
                      variant="neutral-transparent"
                      size="sm"
                      startIcon="media-pause"
                      text="Stoppen met volgen"
                      compactBelowSm
                      accessibleLabel={`Stoppen met volgen van ${debat.onderwerp}`}
                      loading={pendingSessieId === kanaal.sessie_id}
                      disabled={busy}
                      onClick={() => onStop(debat, kanaal)}
                    />
                  ) : (
                    <NlddButton
                      variant="neutral-transparent"
                      size="sm"
                      startIcon="media-play"
                      text="Weer volgen"
                      compactBelowSm
                      accessibleLabel={`${debat.onderwerp} weer volgen`}
                      loading={pendingSessieId === kanaal.sessie_id}
                      disabled={busy}
                      onClick={() => onHervat(kanaal)}
                    />
                  )}
                </nldd-cell>
              </>
            )}
          </Fragment>
        );
      })}
      {kanStarten(debat, kanalen, canStart) && (
        <>
          <nldd-spacer-cell size="16" />
          <nldd-cell horizontal-alignment="right">
            <NlddButton
              variant="secondary"
              size="sm"
              startIcon="microphone"
              text="Kanaal opzetten"
              compactBelowSm
              accessibleLabel={`Kanaal opzetten voor ${debat.onderwerp}`}
              loading={pending}
              disabled={busy}
              onClick={() => onStart(debat)}
            />
          </nldd-cell>
        </>
      )}
    </nldd-list-item>
  );
}

function GevolgdRow({ debat }: { debat: GevolgdDebat }) {
  const badge = afloopBadge(debat);
  return (
    <nldd-list-item>
      <nldd-text-cell text={debat.onderwerp} supporting-text={formatGevolgdRegel(debat)} />
      {badge && (
        <nldd-cell horizontal-alignment="right" hide-below="md">
          <Badge color={badge.color}>{badge.label}</Badge>
        </nldd-cell>
      )}
      {debat.agenda_url && (
        <>
          {badge && <nldd-spacer-cell size="16" hide-below="md" />}
          <nldd-cell horizontal-alignment="right" hide-below="md">
            <nldd-link
              href={debat.agenda_url}
              target="_blank"
              text="Agenda"
              accessible-label={`Agenda van ${debat.onderwerp}`}
            />
          </nldd-cell>
        </>
      )}
      <nldd-spacer-cell size="16" />
      <nldd-cell horizontal-alignment="right">
        <KanaalLink kanaal={debat.kanaal} onderwerp={debat.onderwerp} />
      </nldd-cell>
    </nldd-list-item>
  );
}

/**
 * The debates the teams of this person followed that are over, newest first.
 *
 * Nothing at all while there are none: most people open this page before
 * their team ever followed a debate, and an empty box says nothing to them.
 * The search works on what has been read so far.
 */
function GevolgdSection({ search }: { search: string }) {
  const { data, isLoading, hasNextPage, isFetchingNextPage, fetchNextPage } =
    useGevolgdeDebatten();
  const alle = useMemo(() => gevolgdeDebatten(data?.pages ?? []), [data]);
  const debatten = useMemo(() => filterGevolgd(alle, search), [alle, search]);

  if (isLoading) return <LoadingSpinner padding="32" />;
  if (alle.length === 0) return null;
  // Nothing matches and nothing more to read: the search says so above.
  if (debatten.length === 0 && !hasNextPage) return null;

  return (
    <nldd-container gap="8">
      <nldd-title size={6}><h2>Eerder gevolgd</h2></nldd-title>
      {debatten.length > 0 ? (
        <nldd-list appearance="box-tinted" dividers="always" accessible-label="Debatten die eerder gevolgd zijn">
          {debatten.map((debat) => (
            <GevolgdRow key={debat.sessie_id} debat={debat} />
          ))}
        </nldd-list>
      ) : (
        <nldd-text size="sm" color="secondary">
          Geen eerder gevolgd debat tot nu toe past bij deze zoekterm.
        </nldd-text>
      )}
      {hasNextPage && (
        <nldd-container layout="row" horizontal-alignment="center">
          <NlddButton
            variant="secondary"
            size="sm"
            text="Meer tonen"
            accessibleLabel="Meer eerder gevolgde debatten tonen"
            loading={isFetchingNextPage}
            disabled={isFetchingNextPage}
            onClick={() => void fetchNextPage()}
          />
        </nldd-container>
      )}
    </nldd-container>
  );
}

export function DebattenPage() {
  const { data, isLoading } = useAankomendeDebatten();
  const start = useStartDebat();
  const stop = useStopDebat();
  const hervat = useHervatDebat();
  const { showSuccess, showError } = useToast();
  const [search, setSearch] = useState('');
  // The debate someone pressed stop for, until they confirm or back out.
  const [stopKandidaat, setStopKandidaat] = useState<{
    debat: AankomendDebat;
    kanaal: DebatKanaal;
  } | null>(null);
  const [chosenTeam, setChosenTeam] = useState<string | null>(leesGekozenTeam);

  const teams = useMemo(() => data?.teams ?? [], [data]);
  const team = kiesTeam(teams, chosenTeam);
  const teamId = team?.team_id ?? null;
  // No permission check here, like the Kamerstukken page: the frontend only
  // knows permissions once a person is resolved, and the backend refuses a
  // start that is not allowed.
  const canStart = team?.can_create_channel ?? false;

  const { nu, dagen } = useMemo(
    () => verdeelDebatten(filterDebatten(data?.debatten ?? [], search)),
    [data, search],
  );

  const handleStart = useCallback(
    (debat: AankomendDebat) => {
      if (!teamId) return;
      start.mutate(
        { activiteitId: debat.activiteit_id, teamId },
        {
          onSuccess: (result) => {
            const { tekst, fout } = startMelding(result, team?.team_name);
            (fout ? showError : showSuccess)(tekst);
          },
        },
      );
    },
    [start, teamId, team, showError, showSuccess],
  );

  const handleStop = useCallback((debat: AankomendDebat, kanaal: DebatKanaal) => {
    setStopKandidaat({ debat, kanaal });
  }, []);

  const executeStop = () => {
    const sessieId = stopKandidaat?.kanaal.sessie_id;
    if (!sessieId) return;
    stop.mutate(
      { sessieId },
      {
        onSuccess: () => showSuccess('Het meeluisteren is gestopt. Het kanaal blijft bestaan.'),
        // Also after an error: the toast says what went wrong, and a dialog
        // that stays open would only offer the same button again.
        onSettled: () => setStopKandidaat(null),
      },
    );
  };

  const handleHervat = useCallback(
    (kanaal: DebatKanaal) => {
      if (!kanaal.sessie_id) return;
      hervat.mutate(
        { sessieId: kanaal.sessie_id },
        { onSuccess: () => showSuccess('Het debat wordt weer gevolgd.') },
      );
    },
    [hervat, showSuccess],
  );

  // Only without data. A refetch that fails in the background (after a
  // start, or when the window gets focus) must not wipe a list that is there.
  if (!data) {
    if (isLoading) return <LoadingSpinner padding="64" />;
    return (
      <nldd-container gap="24">
        <EmptyState
          title="De agenda is nu niet op te halen"
          description="Probeer het over een paar minuten opnieuw."
        />
        {/* What was followed comes from our own database, so it is still there. */}
        <GevolgdSection search="" />
      </nldd-container>
    );
  }

  const handleTeam = (teamId: string) => {
    setChosenTeam(teamId);
    bewaarGekozenTeam(teamId);
  };

  const melding =
    data.mattermost_melding ??
    (team && !team.can_create_channel
      ? 'De bot mag in dit team geen kanalen aanmaken. Een Mattermost-beheerder kan dat aanzetten.'
      : null);
  // Several teams and none chosen: say so, instead of a page without buttons.
  const kiesEerst = !data.mattermost_melding && teams.length > 1 && team === null;

  // One thing at a time: a second press while the first is under way would
  // race it.
  const busy = start.isPending || stop.isPending || hervat.isPending;
  const pendingSessieId =
    (stop.isPending ? stop.variables?.sessieId : null) ??
    (hervat.isPending ? hervat.variables?.sessieId : null) ??
    null;
  const renderRow = (debat: AankomendDebat) => (
    <DebatRow
      key={debat.activiteit_id}
      debat={debat}
      teamId={teamId}
      canStart={canStart}
      pending={start.isPending && start.variables?.activiteitId === debat.activiteit_id}
      busy={busy}
      pendingSessieId={pendingSessieId}
      onStart={handleStart}
      onStop={handleStop}
      onHervat={handleHervat}
    />
  );

  return (
    <nldd-container gap="24">
      <nldd-toolbar accessible-label="Debatten filteren">
        <nldd-toolbar-item slot="start" priority={1} min-width="60%">
          {/* Bottom-aligned, each field in a fixed-width container: the team
              field carries a label above it and the search field does not, so
              centring would put them at different heights. A labelled Select
              is a form field that takes the full width it is given; without
              the container it drops onto a line of its own. */}
          <nldd-container layout="wrap" gap="12" vertical-alignment="bottom">
            <nldd-container width="320px">
              <DebatSearchField value={search} onChange={setSearch} />
            </nldd-container>
            {teams.length > 1 && (
              <nldd-container width="256px">
                <Select
                  label="Kanaal komt in team"
                  placeholder="Kies een team"
                  // The choice is needed before anything can be started, and
                  // without `required` the field labels itself "Optioneel".
                  required
                  value={teamId ?? ''}
                  onChange={(e) => handleTeam(e.target.value)}
                  options={teams.map((t) => ({ value: t.team_id, label: t.team_name ?? t.team_id }))}
                />
              </nldd-container>
            )}
          </nldd-container>
        </nldd-toolbar-item>
      </nldd-toolbar>

      {melding && (
        <nldd-text size="sm" color="secondary">
          {melding} Kanalen opzetten kan hier nu niet; de agenda hieronder klopt wel.
        </nldd-text>
      )}

      {kiesEerst && (
        <nldd-text size="sm" color="secondary">
          Kies hierboven eerst het Mattermost-team waar het kanaal in moet komen. Daarna
          verschijnt per vergadering de knop om een kanaal op te zetten.
        </nldd-text>
      )}

      {nu.length > 0 && (
        <nldd-container gap="8">
          <nldd-title size={6}><h2>Nu bezig</h2></nldd-title>
          <nldd-list appearance="box-tinted" dividers="always" accessible-label="Debatten die nu bezig zijn">
            {nu.map(renderRow)}
          </nldd-list>
        </nldd-container>
      )}

      {nu.length > 0 && dagen.length === 0 ? null : dagen.length === 0 ? (
        <EmptyState
          title="Geen debatten gevonden"
          description={
            search
              ? 'Geen komende vergadering past bij deze zoekterm.'
              : 'Er staan de komende weken geen openbare vergaderingen op de agenda.'
          }
        />
      ) : (
        dagen.map((dag) => (
          <nldd-container key={dag.key} gap="8">
            <nldd-title size={6}><h2>{dag.label}</h2></nldd-title>
            <nldd-list appearance="box-tinted" dividers="always" accessible-label={`Debatten op ${dag.label}`}>
              {dag.debatten.map(renderRow)}
            </nldd-list>
          </nldd-container>
        ))
      )}

      <GevolgdSection search={search} />

      <ConfirmDialog
        open={!!stopKandidaat}
        onClose={() => setStopKandidaat(null)}
        onConfirm={executeStop}
        title="Stoppen met volgen"
        confirmLabel="Stoppen met volgen"
        cancelLabel="Blijven volgen"
        loading={stop.isPending}
      >
        {stopKandidaat
          ? `De bot stopt met meeluisteren bij ${stopKandidaat.debat.onderwerp} en zet geen tijdlijn en geen tekst meer in ~${stopKandidaat.kanaal.channel_name}. Het kanaal blijft bestaan, en zolang het debat loopt kun je het volgen hervatten.`
          : ''}
      </ConfirmDialog>
    </nldd-container>
  );
}
