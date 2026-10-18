import {
  useMattermostChannelOverview,
  type MattermostChannelOverview as Channel,
} from '@/hooks/useAdmin';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';

function formatRelative(iso: string | null): string {
  if (!iso) return 'nog niets gezien';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return `${Math.round(ms / 1000)}s geleden`;
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)} min geleden`;
  if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)} uur geleden`;
  return `${Math.round(ms / 86_400_000)} dagen geleden`;
}

function scopeText(channel: Channel): string {
  const label = channel.scope_label ?? '(niet gevonden)';
  const prefix = channel.scope_type === 'lead' ? 'Lead' : 'Initiatief';
  return `${prefix}: ${label}`;
}

/** De vier schakelaars van een koppeling, in de volgorde van de kaart.
 *
 * De tekst is korter dan het label op de checkbox ("Kamerstuk-alerts"
 * wordt "Kamerstukken"), want er passen er vier naast elkaar in deze
 * kolom. Elke schakelaar krijgt een eigen tag in plaats van één
 * samengestelde regel: met drie of vier actieve schakelaars liep die
 * regel de kolom uit.
 */
const MODES = [
  { key: 'auto_note_enabled', text: 'Notities' },
  { key: 'suggest_leads_enabled', text: 'Leads' },
  { key: 'parlementaire_alerts_enabled', text: 'Kamerstukken' },
  { key: 'nieuws_alerts_enabled', text: 'Nieuws' },
] as const satisfies ReadonlyArray<{ key: keyof Channel; text: string }>;

function modeCell(channel: Channel) {
  if (channel.disabled_at) {
    return <nldd-tag text="Uitgeschakeld" icon="dismiss-circle" color="critical" size="sm" />;
  }
  const actief = MODES.filter((mode) => channel[mode.key]);
  if (actief.length === 0) {
    return <nldd-tag text="Niets actief" icon="minus-circle" color="neutral" size="sm" />;
  }
  return (
    <nldd-container layout="wrap" gap="4" width="full" vertical-alignment="center">
      {actief.map((mode) => (
        <nldd-tag key={mode.key} text={mode.text} color="success" size="sm" />
      ))}
    </nldd-container>
  );
}

function ChannelRow({ channel }: { channel: Channel }) {
  return (
    <nldd-table-row>
      {/* Het team erbij, want twee kanalen in verschillende teams mogen
          dezelfde naam dragen en dit overzicht zet ze onder elkaar.
          Zonder die regel is niet te zien welke rij welk kanaal is. */}
      <nldd-title-cell
        text={`#${channel.channel_display_name}`}
        supporting-text={
          channel.team_name ? `${channel.channel_name} · ${channel.team_name}` : channel.channel_name
        }
      />
      <nldd-text-cell text={scopeText(channel)} />
      <nldd-text-cell>{modeCell(channel)}</nldd-text-cell>
      <nldd-text-cell text={formatRelative(channel.last_seen_post_at)} color="secondary" hide-below="md" />
    </nldd-table-row>
  );
}

export function MattermostChannelOverviewTable() {
  const { data, isLoading, error } = useMattermostChannelOverview();

  if (isLoading) {
    return <LoadingSpinner size="sm" padding="16" />;
  }
  if (error) {
    return <nldd-text size="sm" color="critical">Kon kanaaloverzicht niet ophalen.</nldd-text>;
  }
  if (!data || data.length === 0) {
    return (
      <nldd-container gap="8">
        <nldd-title size={4}><h3>Mattermost-kanalen</h3></nldd-title>
        <EmptyState
          icon="message-rectangle-text"
          title="Nog geen kanalen gekoppeld"
          description="Koppel er eentje vanuit een lead of initiatief om hier een overzicht te zien."
        />
      </nldd-container>
    );
  }

  return (
    <nldd-container gap="12">
      <nldd-container gap="4">
        <nldd-title size={4}><h3>Mattermost-kanalen</h3></nldd-title>
        <nldd-text size="sm" color="secondary">
          Gekoppelde kanalen waar de bot meeleest. &quot;Laatste post&quot; is de meest recente
          verwerkte post; ontbreekt deze, dan is er sinds de koppeling niets binnengekomen, of de
          websocket loopt niet.
        </nldd-text>
      </nldd-container>
      <nldd-table
        columns="minmax(200px,1fr) minmax(160px,1fr) minmax(200px,240px) 140px"
        sm-columns="1fr 200px"
        accessible-label="Mattermost-kanalen"
      >
        <nldd-table-row slot="header">
          <nldd-text-cell text="Kanaal" />
          <nldd-text-cell text="Gekoppeld aan" hide-below="md" />
          <nldd-text-cell text="Modus" />
          <nldd-text-cell text="Laatste post" hide-below="md" />
        </nldd-table-row>
        {data.map((c) => (
          <ChannelRow key={c.id} channel={c} />
        ))}
        <div slot="empty">
          <EmptyState icon="message-rectangle-text" title="Nog geen kanalen gekoppeld" />
        </div>
      </nldd-table>
    </nldd-container>
  );
}
