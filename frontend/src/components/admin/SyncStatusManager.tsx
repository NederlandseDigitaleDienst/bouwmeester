import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getSyncStatus,
  getSyncLog,
  triggerSync,
  triggerAllSyncs,
  SYNC_LABELS,
  type SyncEndpoint,
} from '@/api/syncStatus';
import { Card } from '@/components/common/Card';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { NlddButton } from '@/components/nldd/NlddButton';

const ENDPOINTS: SyncEndpoint[] = [
  'tooi',
  'ministeries-csv',
  'rio',
  'organogram',
  'tk-personen',
  'kabinet',
  'abd',
  'historische-kabinetten',
  'onderwijsinstellingen',
  'wikidata-qid',
];

// Mapping van sync-endpoint naar bron-key in tooi_sync_log
const ENDPOINT_NAAR_BRON: Record<SyncEndpoint, string> = {
  'tooi': 'tooi',
  'ministeries-csv': 'ministeries_csv',
  'rio': 'rio',
  'organogram': 'organogram',
  'tk-personen': 'tk_odata',
  'kabinet': 'kabinet',
  'abd': 'abd_scrape',
  'historische-kabinetten': 'kabinet',
  'onderwijsinstellingen': 'onderwijs',
  'wikidata-qid': 'wikidata',
};

const LOG_ACTION_COLOR: Record<string, 'success' | 'warning' | 'critical' | 'neutral'> = {
  add: 'success',
  soft_delete: 'warning',
  conflict: 'critical',
};

function relatieveTijd(iso: string): string {
  const dt = new Date(iso);
  const ms = Date.now() - dt.getTime();
  const min = Math.floor(ms / 60000);
  if (min < 1) return 'zojuist';
  if (min < 60) return `${min} min geleden`;
  const u = Math.floor(min / 60);
  if (u < 24) return `${u} uur geleden`;
  const d = Math.floor(u / 24);
  return `${d} dagen geleden`;
}

export function SyncStatusManager() {
  const queryClient = useQueryClient();
  const [busyEndpoint, setBusyEndpoint] = useState<SyncEndpoint | 'all' | null>(
    null,
  );
  const [expandedBron, setExpandedBron] = useState<string | null>(null);

  const { data: logEntries = [] } = useQuery({
    queryKey: ['sync-log', expandedBron],
    queryFn: () => getSyncLog(expandedBron ?? undefined, 30),
    enabled: expandedBron !== null,
  });

  const { data, isLoading } = useQuery({
    queryKey: ['sync-status'],
    queryFn: getSyncStatus,
    refetchInterval: 30_000,
  });

  const runMutation = useMutation({
    mutationFn: async (endpoint: SyncEndpoint) => {
      setBusyEndpoint(endpoint);
      try {
        return await triggerSync(endpoint);
      } finally {
        setBusyEndpoint(null);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync-status'] });
    },
  });

  const runAllMutation = useMutation({
    mutationFn: async () => {
      setBusyEndpoint('all');
      try {
        return await triggerAllSyncs();
      } finally {
        setBusyEndpoint(null);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync-status'] });
    },
  });

  if (isLoading) return <LoadingSpinner />;

  return (
    <nldd-container gap="16">
      <nldd-container layout="row" gap="16" horizontal-alignment="left">
        <nldd-container width="fit-content" className="row-fill" gap="4">
          <nldd-title size="display-3"><h2>Sync-status overheidsorganisaties</h2></nldd-title>
          <nldd-text size="sm" color="secondary">
            <p>
              Per externe bron: laatste sync-tijdstip + handmatige trigger. Worker draait dagelijks
              (TK + kabinet + ABD) en wekelijks (TOOI + RIO + CSV + organogram).
            </p>
          </nldd-text>
        </nldd-container>
        <NlddButton
          variant="primary"
          text="Alles syncen"
          startIcon="refresh"
          loading={busyEndpoint === 'all'}
          onClick={() => runAllMutation.mutate()}
          disabled={busyEndpoint !== null}
        />
      </nldd-container>

      {data && (
        <nldd-container layout="grid" column-count={4} gap="12">
          {Object.entries(data.actief_per_bron).map(([bron, count]) => (
            <Card key={bron}>
              <nldd-container gap="0">
                <nldd-text size="xs" color="secondary"><p>Actief — {bron}</p></nldd-text>
                <nldd-text size="lg" weight="bold"><p>{count}</p></nldd-text>
              </nldd-container>
            </Card>
          ))}
          <Card>
            <nldd-container gap="0">
              <nldd-text size="xs" color="secondary"><p>Open conflicten</p></nldd-text>
              <nldd-text size="lg" weight="bold"><p>{data.open_reconciliations}</p></nldd-text>
            </nldd-container>
          </Card>
        </nldd-container>
      )}

      <nldd-table
        columns="minmax(200px,1fr) minmax(160px,1fr) 96px"
        accessible-label="Sync-status per bron"
      >
        <nldd-table-row slot="header">
          <nldd-text-cell text="Bron" />
          <nldd-text-cell text="Laatste run" />
          <nldd-text-cell />
        </nldd-table-row>
        {ENDPOINTS.map((ep) => {
          const bron = ENDPOINT_NAAR_BRON[ep];
          const laatste = data?.laatste_run_per_bron[bron];
          const isExpanded = expandedBron === bron;
          return (
            <nldd-table-row key={ep}>
              <nldd-text-cell>
                <NlddButton
                  variant="neutral-transparent"
                  size="sm"
                  text={SYNC_LABELS[ep]}
                  startIcon={isExpanded ? 'chevron-down' : 'chevron-right'}
                  onClick={() => setExpandedBron(isExpanded ? null : bron)}
                />
              </nldd-text-cell>
              <nldd-text-cell
                text={
                  laatste
                    ? `${relatieveTijd(laatste)} (${new Date(laatste).toLocaleString('nl-NL')})`
                    : '—'
                }
                color="secondary"
              />
              <nldd-text-cell>
                <NlddButton
                  variant="secondary"
                  size="sm"
                  text="Run"
                  startIcon={busyEndpoint === ep ? 'refresh' : 'media-play'}
                  loading={busyEndpoint === ep}
                  onClick={() => runMutation.mutate(ep)}
                  disabled={busyEndpoint !== null}
                />
              </nldd-text-cell>
              {isExpanded && (
                <div style={{ gridColumn: '1 / -1' }}>
                  <nldd-box>
                    <nldd-container padding="12" gap="8">
                      <nldd-text size="xs" color="secondary"><p>Recente log-entries (laatste 30):</p></nldd-text>
                      {logEntries.length === 0 ? (
                        <nldd-text size="xs" color="secondary"><p>Geen entries.</p></nldd-text>
                      ) : (
                        <nldd-container gap="4" style={{ maxHeight: '240px', overflowY: 'auto' }}>
                          {logEntries.map((entry) => (
                            <nldd-container key={entry.id} layout="row" gap="8" vertical-alignment="top">
                              <nldd-container width="128px">
                                <nldd-text size="xs" color="secondary">
                                  <p>{new Date(entry.created_at).toLocaleString('nl-NL')}</p>
                                </nldd-text>
                              </nldd-container>
                              <nldd-tag
                                text={entry.action}
                                color={LOG_ACTION_COLOR[entry.action] ?? 'neutral'}
                                size="sm"
                              />
                              <nldd-text size="xs">
                                <p>
                                  {entry.note ||
                                    (entry.after && typeof entry.after.naam === 'string'
                                      ? entry.after.naam
                                      : entry.tooi_uri || '—')}
                                </p>
                              </nldd-text>
                            </nldd-container>
                          ))}
                        </nldd-container>
                      )}
                    </nldd-container>
                  </nldd-box>
                </div>
              )}
            </nldd-table-row>
          );
        })}
      </nldd-table>
    </nldd-container>
  );
}
