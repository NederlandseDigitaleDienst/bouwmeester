import { apiDelete, apiGet, apiPatch, apiPost } from './client';

export interface MattermostChannelLink {
  id: string;
  channel_id: string;
  channel_name: string;
  channel_display_name: string;
  team_id: string | null;
  team_name?: string | null;
  scope_type: 'initiatief' | 'lead';
  scope_id: string;
  auto_note_enabled: boolean;
  suggest_leads_enabled: boolean;
  /** Kamerstukken die op een zoekterm van dit initiatief matchen. */
  parlementaire_alerts_enabled: boolean;
  nieuws_alerts_enabled: boolean;
  last_seen_post_at: number | null;
  disabled_at: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface MattermostChannelSearchResult {
  channel_id: string;
  channel_name: string;
  channel_display_name: string;
  team_id: string | null;
  team_name?: string | null;
  member_count: number | null;
  is_bot_member: boolean;
}

export interface MattermostChannelLinkCreate {
  channel_id: string;
  channel_name: string;
  channel_display_name: string;
  team_id?: string | null;
  team_name?: string | null;
  auto_note_enabled?: boolean;
  suggest_leads_enabled?: boolean;
  parlementaire_alerts_enabled?: boolean;
  nieuws_alerts_enabled?: boolean;
}

export interface MattermostChannelLinkUpdate {
  auto_note_enabled?: boolean;
  suggest_leads_enabled?: boolean;
  parlementaire_alerts_enabled?: boolean;
  nieuws_alerts_enabled?: boolean;
  /** Alleen ``true`` is geldig; backend rejecteert ``false``. */
  reenable?: true;
}

export async function listInitiatiefChannels(
  initiatiefId: string,
): Promise<MattermostChannelLink[]> {
  return apiGet<MattermostChannelLink[]>(
    `/api/initiatieven/${initiatiefId}/mattermost-channels`,
  );
}

export async function listLeadChannels(
  leadId: string,
): Promise<MattermostChannelLink[]> {
  return apiGet<MattermostChannelLink[]>(
    `/api/leads/${leadId}/mattermost-channels`,
  );
}

export async function createInitiatiefChannelLink(
  initiatiefId: string,
  data: MattermostChannelLinkCreate,
): Promise<MattermostChannelLink> {
  return apiPost<MattermostChannelLink>(
    `/api/initiatieven/${initiatiefId}/mattermost-channels`,
    data,
  );
}

export async function createLeadChannelLink(
  leadId: string,
  data: MattermostChannelLinkCreate,
): Promise<MattermostChannelLink> {
  return apiPost<MattermostChannelLink>(
    `/api/leads/${leadId}/mattermost-channels`,
    data,
  );
}

export async function updateChannelLink(
  linkId: string,
  data: MattermostChannelLinkUpdate,
): Promise<MattermostChannelLink> {
  return apiPatch<MattermostChannelLink>(
    `/api/mattermost-channels/${linkId}`,
    data,
  );
}

export async function deleteChannelLink(linkId: string): Promise<void> {
  return apiDelete(`/api/mattermost-channels/${linkId}`);
}

export async function searchMattermostChannels(
  q: string,
): Promise<MattermostChannelSearchResult[]> {
  return apiGet<MattermostChannelSearchResult[]>(
    '/api/mattermost-channels/search',
    { q },
  );
}
