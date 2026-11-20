import { useWorkerHealth, type WorkerHealth, type WorkerHeartbeat } from '@/hooks/useAdmin';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';

const LOOP_LABELS: Record<string, string> = {
  parlementair: 'Parlementaire import',
  mattermost_websocket: 'Mattermost: websocket (kanaal-meelezen + DM-koppeling)',
  opdracht_task: 'Opdracht-taken (deadlines, budget)',
  fcc_sync: 'Fortes Change Cloud sync',
  mattermost_retry: 'Mattermost: herverwerking na LLM-storing',
  overheidsorganisaties_daily: 'Overheidsorganisaties: dagelijks (TK-leden, kabinet, ABD)',
  overheidsorganisaties_weekly: 'Overheidsorganisaties: wekelijks (TOOI, RIO, organogram)',
  worker_singleton: 'Worker-singleton (lock)',
};

function formatAge(seconds: number | null): string {
  if (seconds === null) return '–';
  if (seconds < 90) return `${Math.round(seconds)}s geleden`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min geleden`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} uur geleden`;
  return `${Math.round(seconds / 86400)} dagen geleden`;
}

const HEALTH_CONFIG: Record<WorkerHealth, { icon: string; color: 'success' | 'warning' | 'critical' | 'neutral'; label: string }> = {
  healthy: { icon: 'check-mark-circle', color: 'success', label: 'Draait' },
  stale: { icon: 'exclamation-triangle', color: 'warning', label: 'Vertraagd' },
  down: { icon: 'dismiss-circle', color: 'critical', label: 'Niet actief' },
  disabled: { icon: 'minus-circle', color: 'neutral', label: 'Uitgeschakeld' },
};

function HealthBadge({ health, one_shot = false }: { health: WorkerHealth; one_shot?: boolean }) {
  const { icon, color, label } = HEALTH_CONFIG[health];
  // Een lock "draait" niet, die is gehouden.
  return (
    <nldd-tag
      text={health === 'healthy' && one_shot ? 'Actief' : label}
      icon={icon}
      color={color}
      size="sm"
    />
  );
}

function WorkerRow({ worker }: { worker: WorkerHeartbeat }) {
  const label = LOOP_LABELS[worker.loop_name] ?? worker.loop_name;
  const age = formatAge(worker.seconds_since_last_tick);
  return (
    <nldd-table-row>
      <nldd-title-cell text={label} supporting-text={worker.loop_name} />
      <nldd-text-cell>
        <HealthBadge health={worker.health} one_shot={worker.one_shot} />
      </nldd-text-cell>
      {/* Een one-shot tickt per ontwerp maar één keer, dus de leeftijd is
          "sinds wanneer", niet een achterstallige hartslag. */}
      <nldd-text-cell
        text={
          worker.one_shot && worker.seconds_since_last_tick !== null
            ? `sinds ${age.replace(/ geleden$/, '')}`
            : age
        }
        hide-below="md"
      />
      <nldd-text-cell
        text={worker.status === 'never_started' ? 'Nooit gestart' : worker.status}
        color={worker.status === 'never_started' ? 'critical' : 'secondary'}
        supporting-text={worker.detail ?? undefined}
        hide-below="lg"
      />
    </nldd-table-row>
  );
}

export function WorkerHealthTable() {
  const { data, isLoading, error } = useWorkerHealth();

  if (isLoading) {
    return <LoadingSpinner size="sm" padding="16" />;
  }
  if (error) {
    return (
      <nldd-text size="sm" color="critical"><p>Kon worker-status niet ophalen.</p></nldd-text>
    );
  }
  if (!data || data.workers.length === 0) {
    return (
      <nldd-text size="sm" color="secondary"><p>Geen worker-data beschikbaar.</p></nldd-text>
    );
  }

  const downWorkers = data.workers.filter((w) => w.health === 'down');

  return (
    <nldd-container gap="12">
      <nldd-container gap="4">
        <nldd-title size="display-4"><h3>Achtergrondprocessen</h3></nldd-title>
        <nldd-text size="sm" color="secondary">
          <p>
            De worker draait naast de webserver en doet polling, sync en de Mattermost-websocket. Elke
            loop schrijft hier een hartslag.
          </p>
        </nldd-text>
      </nldd-container>

      {downWorkers.length > 0 ? (
        <nldd-inline-dialog
          variant="alert"
          text={
            downWorkers.length === 1 ? 'Deze loop draait niet' : 'Deze loops draaien niet'
          }
          supporting-text={`${downWorkers
            .map((w) => LOOP_LABELS[w.loop_name] ?? w.loop_name)
            .join(', ')}. De bijbehorende functionaliteit werkt nu mogelijk niet. Check de container-logs voor de oorzaak.`}
        />
      ) : null}

      <nldd-table
        columns="minmax(200px,1fr) 140px 160px minmax(160px,1fr)"
        sm-columns="1fr 140px"
        md-columns="1fr 140px 160px"
        accessible-label="Status achtergrondprocessen"
      >
        <nldd-table-row slot="header">
          <nldd-text-cell text="Loop" />
          <nldd-text-cell text="Status" />
          <nldd-text-cell text="Laatste hartslag" hide-below="md" />
          <nldd-text-cell text="Detail" hide-below="lg" />
        </nldd-table-row>
        {data.workers.map((w) => (
          <WorkerRow key={w.loop_name} worker={w} />
        ))}
        <div slot="empty">
          <EmptyState icon="inbox" title="Geen worker-data beschikbaar" />
        </div>
      </nldd-table>

      <nldd-text size="xs" color="secondary">
        <p>
          Server-tijd: {new Date(data.server_now).toLocaleString('nl-NL')}. Auto-refresh elke 15 sec.
        </p>
      </nldd-text>
    </nldd-container>
  );
}
