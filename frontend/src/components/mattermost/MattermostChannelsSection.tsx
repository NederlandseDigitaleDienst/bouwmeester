import { useMemo, useRef, useState } from 'react';
import { Modal } from '@/components/common/Modal';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Icon } from '@/components/nldd/Icon';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, orUndef, useNlddEvent } from '@/components/nldd/events';
import { useDebounce } from '@/hooks/useDebounce';
import {
  useCreateInitiatiefChannelLink,
  useCreateLeadChannelLink,
  useDeleteChannelLink,
  useInitiatiefChannels,
  useLeadChannels,
  useSearchMattermostChannels,
  useUpdateChannelLink,
} from '@/hooks/useMattermostChannels';
import type {
  MattermostChannelLink,
  MattermostChannelSearchResult,
} from '@/api/mattermostChannels';
import { NlddButton } from '@/components/nldd/NlddButton';

type Scope =
  | { type: 'initiatief'; id: string }
  | { type: 'lead'; id: string };

interface Props {
  scope: Scope;
}

export function MattermostChannelsSection({ scope }: Props) {
  const initiatiefQuery = useInitiatiefChannels(
    scope.type === 'initiatief' ? scope.id : undefined,
  );
  const leadQuery = useLeadChannels(
    scope.type === 'lead' ? scope.id : undefined,
  );
  const query = scope.type === 'initiatief' ? initiatiefQuery : leadQuery;
  const [pickerOpen, setPickerOpen] = useState(false);

  const updateMutation = useUpdateChannelLink(scope);
  const deleteMutation = useDeleteChannelLink(scope);

  return (
    <nldd-card>
      {/* `padding="16"`, zoals de andere secties in deze modal. Zonder plakte
          de kop met zijn knop tegen de boven- en rechterrand van de kaart. */}
      <nldd-container gap="12" padding="16">
      <nldd-container layout="row" gap="8" vertical-alignment="center">
        {/* A container defaults to width:full, so in a row beside a button it
            takes a hard 100% and the button is squeezed below its own label:
            two lines of text in a 48px block where a 32px button belongs.
            `fit-content` plus `row-fill` makes it take what is left over
            instead, which is what a heading beside an action wants. */}
        {/* Zelfde kopschaal als de andere kaarten op de initiatiefpagina
            (Zoektermen, Context, Publieke pagina). Stond hier als `<h4>`
            uit de tijd dat deze sectie alleen in een modal hing; naast
            die kaarten las hij als het hoofdonderwerp van de pagina. */}
        <nldd-container width="fit-content" className="row-fill">
          <nldd-container layout="row" gap="6" vertical-alignment="center">
            <Icon name="tag" size="sm" />
            <nldd-text size="xs" weight="bold" color="secondary">
              Mattermost-kanalen
            </nldd-text>
          </nldd-container>
        </nldd-container>
        <NlddButton variant="secondary" size="sm" startIcon="plus" onClick={() => setPickerOpen(true)} text="Kanaal koppelen" />
      </nldd-container>

      {query.isLoading && (
        <nldd-container padding-block="24">
          <LoadingSpinner />
        </nldd-container>
      )}
      {query.isError && (
        <nldd-inline-dialog
          variant="alert"
          size="md"
          text="Kon kanalen niet ophalen."
        />
      )}
      {query.data && query.data.length === 0 && (
        <nldd-inline-dialog
          text={
            scope.type === 'initiatief'
              ? 'Nog geen kanalen gekoppeld.'
              : 'Nog geen kanaal gekoppeld.'
          }
          supporting-text={
            scope.type === 'initiatief'
              ? 'Bouwmeester leest mee in gekoppelde kanalen en stelt nieuwe leads voor.'
              : 'Berichten in gekoppelde kanalen worden notities op deze lead.'
          }
        />
      )}
      {query.data && query.data.length > 0 && (
        <nldd-list type="list" variant="box-tinted" accessible-label="Gekoppelde kanalen">
          {query.data.map((link) => (
            <ChannelRow
              key={link.id}
              link={link}
              onToggleAutoNote={(value) =>
                updateMutation.mutate({
                  linkId: link.id,
                  data: { auto_note_enabled: value },
                })
              }
              onToggleSuggest={(value) =>
                updateMutation.mutate({
                  linkId: link.id,
                  data: { suggest_leads_enabled: value },
                })
              }
              onToggleAlerts={(value) =>
                updateMutation.mutate({
                  linkId: link.id,
                  data: { parlementaire_alerts_enabled: value },
                })
              }
              onToggleNieuws={(value) =>
                updateMutation.mutate({
                  linkId: link.id,
                  data: { nieuws_alerts_enabled: value },
                })
              }
              onDelete={() => deleteMutation.mutate(link.id)}
            />
          ))}
        </nldd-list>
      )}

      <ChannelPickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        scope={scope}
      />
      </nldd-container>
    </nldd-card>
  );
}

/** Reads `checked` off an nldd-checkbox-field's `change` detail. */
function checkedValue(event: Event): boolean {
  return Boolean((event as CustomEvent<{ checked?: boolean }>).detail?.checked);
}

function ChannelRow({
  link,
  onToggleAutoNote,
  onToggleSuggest,
  onToggleAlerts,
  onToggleNieuws,
  onDelete,
}: {
  link: MattermostChannelLink;
  onToggleAutoNote: (value: boolean) => void;
  onToggleSuggest: (value: boolean) => void;
  onToggleAlerts: (value: boolean) => void;
  onToggleNieuws: (value: boolean) => void;
  onDelete: () => void;
}) {
  const autoNoteRef = useRef<HTMLElement>(null);
  const suggestRef = useRef<HTMLElement>(null);
  const alertsRef = useRef<HTMLElement>(null);
  const nieuwsRef = useRef<HTMLElement>(null);
  useNlddEvent(autoNoteRef, 'change', (e) => onToggleAutoNote(checkedValue(e)));
  useNlddEvent(suggestRef, 'change', (e) => onToggleSuggest(checkedValue(e)));
  useNlddEvent(alertsRef, 'change', (e) => onToggleAlerts(checkedValue(e)));
  useNlddEvent(nieuwsRef, 'change', (e) => onToggleNieuws(checkedValue(e)));

  return (
    <nldd-list-item>
      <nldd-container layout="row" width="full" gap="12" horizontal-alignment="right" vertical-alignment="top" padding="4">
        <nldd-container width="full" min-width="0" gap="4">
          <nldd-container layout="row" gap="8" vertical-alignment="center">
            <nldd-icon-cell icon="tag" size="16" />
            <nldd-text-cell text={link.channel_display_name} width="fit-content" />
            {/* Zelfde reden als in de picker: zonder het team is niet te
                zien welk van twee gelijknamige kanalen hier hangt. */}
            {link.team_name && (
              <nldd-text size="xs" color="secondary">
                {link.team_name}
              </nldd-text>
            )}
            {link.disabled_at && <nldd-tag color="critical" size="sm" text="uitgeschakeld" />}
          </nldd-container>
          <nldd-container layout="wrap" gap="16">
            <nldd-checkbox-field
              ref={autoNoteRef}
              label="Berichten als notities"
              checked={orUndef(link.auto_note_enabled)}
            />
            <nldd-checkbox-field
              ref={suggestRef}
              label="Leads voorstellen"
              checked={orUndef(link.suggest_leads_enabled)}
            />
            {/* Kamerstukken die op een zoekterm van dit initiatief matchen.
                Standaard uit: een kanaal dat voor leads is gekoppeld hoort
                niet ongevraagd elk kamerstuk te krijgen. De zoektermen zelf
                staan onder "Parlementaire signalen". */}
            <nldd-checkbox-field
              ref={alertsRef}
              label="Kamerstuk-alerts"
              checked={orUndef(link.parlementaire_alerts_enabled)}
            />
            {/* Artikelen uit de vakpers op dezelfde zoektermen. Apart van
                de kamerstukken: dat zijn andere stukken voor een ander
                gesprek, en een kanaal dat de Kamer volgt heeft niet
                vanzelf om nieuws gevraagd. */}
            <nldd-checkbox-field
              ref={nieuwsRef}
              label="Nieuws-alerts"
              checked={orUndef(link.nieuws_alerts_enabled)}
            />
          </nldd-container>
        </nldd-container>
        <NlddIconButton
          icon="trash"
          accessibleLabel="Ontkoppelen"
          variant="neutral-transparent"
          size="sm"
          onClick={onDelete}
        />
      </nldd-container>
    </nldd-list-item>
  );
}

function ChannelPickerModal({
  open,
  onClose,
  scope,
}: {
  open: boolean;
  onClose: () => void;
  scope: Scope;
}) {
  const [q, setQ] = useState('');
  const debounced = useDebounce(q, 250);
  const search = useSearchMattermostChannels(debounced);
  const createInit = useCreateInitiatiefChannelLink(
    scope.type === 'initiatief' ? scope.id : undefined,
  );
  const createLead = useCreateLeadChannelLink(
    scope.type === 'lead' ? scope.id : undefined,
  );
  const createMutation = scope.type === 'initiatief' ? createInit : createLead;
  const errorMsg = useMemo(() => {
    if (search.isError) {
      const err = search.error as { message?: string } | undefined;
      return err?.message ?? 'Kon Mattermost niet bereiken.';
    }
    return null;
  }, [search.isError, search.error]);

  const handlePick = (ch: MattermostChannelSearchResult) => {
    createMutation.mutate(
      {
        channel_id: ch.channel_id,
        channel_name: ch.channel_name,
        channel_display_name: ch.channel_display_name,
        team_id: ch.team_id,
      },
      {
        onSuccess: () => {
          setQ('');
          onClose();
        },
      },
    );
  };

  const searchRef = useRef<HTMLElement>(null);
  useNlddEvent(searchRef, 'input', (e) => setQ(eventValue(e)));

  return (
    <Modal open={open} onClose={onClose} title="Kanaal koppelen">
      <nldd-container gap="12">
        <nldd-text size="xs" color="secondary">
          Zoek een kanaal waar de Bouwmeester-bot al lid van is. Niet
          gevonden? Voeg de bot eerst toe aan dat kanaal in Mattermost.
        </nldd-text>
        <nldd-text-field
          ref={searchRef}
          value={q}
          placeholder="Zoek op kanaalnaam"
          keyboard="search"
          accessible-label="Zoek op kanaalnaam"
        />
        {errorMsg && <nldd-inline-dialog variant="alert" text={errorMsg} />}
        {search.isLoading && (
          <nldd-container padding-block="16">
            <LoadingSpinner />
          </nldd-container>
        )}
        {search.data && search.data.length === 0 && debounced.length >= 2 && (
          <nldd-inline-dialog text={`Geen kanalen gevonden voor "${debounced}".`} />
        )}
        {search.data && search.data.length > 0 && (
          <nldd-list
            type="list"
            variant="box-tinted"
            height="288px"
            accessible-label="Gevonden kanalen"
          >
            {search.data.map((ch) => (
              <ChannelSearchRow
                key={ch.channel_id}
                channel={ch}
                pending={createMutation.isPending}
                onPick={() => handlePick(ch)}
              />
            ))}
          </nldd-list>
        )}
        {createMutation.isError && (
          <nldd-inline-dialog
            variant="alert"
            text="Koppelen mislukt"
            supporting-text={
              (createMutation.error as { message?: string } | undefined)?.message ??
              'onbekende fout'
            }
          />
        )}
        <nldd-container layout="row" horizontal-alignment="right" padding-top="8">
          <nldd-link
            href="https://docs.mattermost.com/welcome/managing-members.html"
            target="_blank"
            size="xs"
            end-icon="external-link"
            text="Bot toevoegen aan kanaal"
          />
        </nldd-container>
      </nldd-container>
    </Modal>
  );
}

function ChannelSearchRow({
  channel,
  pending,
  onPick,
}: {
  channel: MattermostChannelSearchResult;
  pending: boolean;
  onPick: () => void;
}) {
  return (
    <nldd-list-item>
      <nldd-container layout="row" width="full" gap="8" horizontal-alignment="right" vertical-alignment="center">
        {/* Het team erbij, want twee kanalen in verschillende teams mogen
            dezelfde naam dragen. Zonder die regel toont de lijst twee
            identieke rijen met een koppel-knop en is kiezen gokken. */}
        <nldd-text-cell
          text={channel.channel_display_name}
          supporting-text={
            channel.team_name
              ? `${channel.channel_name} · ${channel.team_name}`
              : channel.channel_name
          }
          width="full"
        />
        <NlddButton size="sm" variant="primary" startIcon="link" onClick={onPick} disabled={pending} text="Koppelen" />
      </nldd-container>
    </nldd-list-item>
  );
}
