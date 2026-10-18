import { useQuery } from '@tanstack/react-query';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/api/client';
import { useMutationWithError } from '@/hooks/useMutationWithError';
import { queryKeys } from '@/hooks/queryKeys';
import type { AccessRequest } from '@/types';

export interface WhitelistEmail {
  id: string;
  email: string;
  added_by: string | null;
  created_at: string;
}

export function useWhitelist() {
  return useQuery({
    queryKey: queryKeys.admin.whitelist(),
    queryFn: () => apiGet<WhitelistEmail[]>('/api/admin/whitelist'),
  });
}

export function useAddWhitelistEmail() {
  return useMutationWithError({
    mutationFn: (email: string) =>
      apiPost<WhitelistEmail>('/api/admin/whitelist', { email }),
    errorMessage: 'Fout bij toevoegen van e-mailadres',
    invalidateKeys: [queryKeys.admin.whitelist()],
  });
}

export function useRemoveWhitelistEmail() {
  return useMutationWithError({
    mutationFn: (id: string) => apiDelete(`/api/admin/whitelist/${id}`),
    errorMessage: 'Fout bij verwijderen van e-mailadres',
    invalidateKeys: [queryKeys.admin.whitelist()],
  });
}

export function useAccessRequests(status?: string) {
  return useQuery({
    queryKey: queryKeys.admin.accessRequests(status),
    queryFn: () =>
      apiGet<AccessRequest[]>('/api/admin/access-requests', status ? { status } : undefined),
  });
}

export function useReviewAccessRequest() {
  return useMutationWithError({
    mutationFn: ({ id, action, deny_reason }: { id: string; action: 'approve' | 'deny'; deny_reason?: string }) =>
      apiPatch<AccessRequest>(`/api/admin/access-requests/${id}`, { action, deny_reason }),
    errorMessage: 'Fout bij beoordelen van toegangsverzoek',
    invalidateKeys: [queryKeys.admin.accessRequestsAll(), queryKeys.admin.whitelist()],
  });
}

// ---------------------------------------------------------------------------
// App configuration (LLM keys, model settings)
// ---------------------------------------------------------------------------

export interface AppConfigEntry {
  id: string;
  key: string;
  value: string;
  description: string | null;
  is_secret: boolean;
  updated_by: string | null;
  updated_at: string;
  created_at: string;
}

export function useAppConfig() {
  return useQuery({
    queryKey: queryKeys.admin.config(),
    queryFn: () => apiGet<AppConfigEntry[]>('/api/admin/config'),
  });
}

export function useUpdateAppConfig() {
  return useMutationWithError({
    mutationFn: ({ key, value }: { key: string; value: string }) =>
      apiPatch<AppConfigEntry>(`/api/admin/config/${key}`, { value }),
    errorMessage: 'Fout bij opslaan van configuratie',
    invalidateKeys: [queryKeys.admin.config()],
  });
}

// ---------------------------------------------------------------------------
// Build / deploy info
// ---------------------------------------------------------------------------

export interface VersionInfo {
  git_sha: string;
  build_time: string;
  repo_url: string;
}

export function useVersionInfo() {
  return useQuery({
    queryKey: queryKeys.admin.version(),
    queryFn: () => apiGet<VersionInfo>('/api/admin/version'),
    staleTime: 5 * 60 * 1000,
  });
}

// ---------------------------------------------------------------------------
// Worker health
// ---------------------------------------------------------------------------

export type WorkerHealth = 'healthy' | 'stale' | 'down' | 'disabled';

export interface WorkerHeartbeat {
  loop_name: string;
  status: string;
  detail: string | null;
  last_tick_at: string | null;
  started_at: string | null;
  seconds_since_last_tick: number | null;
  health: WorkerHealth;
  /** Tickt per ontwerp één keer (worker_singleton); leeftijd zegt niets over gezondheid. */
  one_shot: boolean;
}

export interface WorkerHealthResponse {
  workers: WorkerHeartbeat[];
  server_now: string;
}

export function useWorkerHealth() {
  return useQuery({
    queryKey: queryKeys.admin.workers(),
    queryFn: () => apiGet<WorkerHealthResponse>('/api/admin/workers'),
    refetchInterval: 15_000,
  });
}

// ---------------------------------------------------------------------------
// Mattermost channel overview
// ---------------------------------------------------------------------------

export interface MattermostChannelOverview {
  id: string;
  channel_id: string;
  channel_display_name: string;
  channel_name: string;
  team_id?: string | null;
  team_name?: string | null;
  scope_type: 'lead' | 'initiatief';
  scope_id: string;
  scope_label: string | null;
  auto_note_enabled: boolean;
  suggest_leads_enabled: boolean;
  parlementaire_alerts_enabled: boolean;
  nieuws_alerts_enabled: boolean;
  last_seen_post_at: string | null;
  disabled_at: string | null;
  created_at: string;
}

export function useMattermostChannelOverview() {
  return useQuery({
    queryKey: queryKeys.admin.mattermostChannels(),
    queryFn: () => apiGet<MattermostChannelOverview[]>('/api/admin/mattermost-channels'),
    refetchInterval: 30_000,
  });
}
