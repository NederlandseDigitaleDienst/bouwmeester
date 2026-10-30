/**
 * Centralized query key definitions for React Query.
 *
 * Using a factory avoids typos and makes key patterns easy to discover.
 * Prefix keys are useful for broad invalidation (e.g. invalidate all nodes).
 */

import type { ActivityFeedParams, EdgeFilters, LeadFilters, OpdrachtFilters, ParlementairItemFilters, SearchResultType, TaskFilters } from '@/types';

export const queryKeys = {
  // --- Nodes ---
  nodes: {
    all: ['nodes'] as const,
    lists: () => ['nodes', 'list'] as const,
    list: (nodeType?: string, search?: string, limit?: number) => ['nodes', 'list', nodeType, search, limit] as const,
    details: () => ['nodes', 'detail'] as const,
    detail: (id: string | undefined) => ['nodes', 'detail', id] as const,
    neighbors: (id: string | undefined) => ['nodes', 'detail', id, 'neighbors'] as const,
    stakeholders: (id: string | undefined) => ['nodes', 'detail', id, 'stakeholders'] as const,
    titleHistory: (id: string | undefined) => ['nodes', 'detail', id, 'history', 'titles'] as const,
    statusHistory: (id: string | undefined) => ['nodes', 'detail', id, 'history', 'statuses'] as const,
    parlementairItem: (id: string | undefined) => ['nodes', 'detail', id, 'parlementair-item'] as const,
    bronDetail: (id: string | undefined) => ['nodes', 'detail', id, 'bron-detail'] as const,
    bijlage: (id: string | undefined) => ['nodes', 'detail', id, 'bijlage'] as const,
    graph: (id: string | undefined, depth?: number) => ['nodes', 'detail', id, 'graph', depth] as const,
  },

  // --- Tasks ---
  tasks: {
    all: ['tasks'] as const,
    lists: () => ['tasks', 'list'] as const,
    list: (filters?: TaskFilters) => ['tasks', 'list', filters] as const,
    detail: (id: string | null) => ['tasks', 'detail', id] as const,
    /** Alle taakdetails: na verwijderen weet je de hoofdtaak niet. */
    details: () => ['tasks', 'detail'] as const,
    eenheidOverview: (orgId: string | null) => ['tasks', 'list', 'eenheid-overview', orgId] as const,
    byPerson: (personId: string | null) => ['tasks', 'list', 'by-person', personId] as const,
    byOpdracht: (opdrachtId: string | null) => ['tasks', 'list', 'by-opdracht', opdrachtId] as const,
    workTypes: () => ['tasks', 'work-types'] as const,
    comments: (taskId: string | null) => ['tasks', 'detail', taskId, 'comments'] as const,
    attachments: (taskId: string | null) => ['tasks', 'detail', taskId, 'attachments'] as const,
  },

  // --- People ---
  people: {
    all: ['people'] as const,
    detail: (id: string | null) => ['people', id] as const,
    summary: (id: string | null) => ['people', id, 'summary'] as const,
    organisaties: (personId: string | null, actief: boolean) => ['people', personId, 'organisaties', { actief }] as const,
    search: (query: string) => ['people', 'search', query] as const,
    expertiseValues: ['people', 'expertise-values'] as const,
  },

  // --- Organisatie ---
  organisatie: {
    all: ['organisatie'] as const,
    tree: () => ['organisatie', 'tree'] as const,
    flat: () => ['organisatie', 'flat'] as const,
    detail: (id: string | null) => ['organisatie', id] as const,
    personen: (id: string | null) => ['organisatie', id, 'personen'] as const,
    personenRecursive: (id: string | null) => ['organisatie', id, 'personen', 'recursive'] as const,
    managedBy: (personId: string | undefined) => ['organisatie', 'managed-by', personId] as const,
  },

  // --- Tags ---
  tags: {
    all: ['tags'] as const,
    list: (params?: { tree?: boolean; search?: string }) => ['tags', params] as const,
    forNode: (nodeId: string) => ['node-tags', nodeId] as const,
    forLead: (leadId: string) => ['lead-tags', leadId] as const,
  },

  // --- Edges ---
  edges: {
    all: ['edges'] as const,
    list: (filters?: EdgeFilters) => ['edges', filters] as const,
  },

  // --- Edge Types ---
  edgeTypes: {
    all: ['edge-types'] as const,
    valid: (fromNodeType?: string, toNodeType?: string) => ['edge-types', 'valid', fromNodeType, toNodeType] as const,
  },

  // --- Edge Schema Rules ---
  edgeSchemaRules: {
    all: ['edge-schema-rules'] as const,
  },

  // --- Notifications ---
  notifications: {
    all: ['notifications'] as const,
    list: (unreadOnly: boolean) => ['notifications', unreadOnly] as const,
    detail: (id: string | undefined) => ['notifications', 'detail', id] as const,
    count: () => ['notifications', 'count'] as const,
    replies: (notificationId: string | undefined) => ['notifications', 'replies', notificationId] as const,
  },

  // --- Parlementair ---
  parlementair: {
    all: ['parlementair-items'] as const,
    list: (filters?: ParlementairItemFilters) => ['parlementair-items', filters] as const,
    reviewQueue: () => ['parlementair-review-queue'] as const,
  },

  // --- Debatten ---
  debatten: {
    all: ['debatten'] as const,
    aankomend: () => ['debatten', 'aankomend'] as const,
    gevolgd: () => ['debatten', 'gevolgd'] as const,
  },

  // --- FCC ---
  fcc: {
    syncLogs: (opdrachtId?: string) => ['fcc', 'sync-logs', opdrachtId] as const,
    schema: () => ['fcc', 'schema'] as const,
    conflicts: () => ['fcc', 'conflicts'] as const,
    lastSync: () => ['fcc', 'last-sync'] as const,
  },

  // --- Admin ---
  admin: {
    whitelist: () => ['admin', 'whitelist'] as const,
    users: () => ['admin', 'users'] as const,
    accessRequestsAll: () => ['admin', 'access-requests'] as const,
    accessRequests: (status?: string) => ['admin', 'access-requests', status] as const,
    config: () => ['admin', 'config'] as const,
    sharing: () => ['admin', 'sharing'] as const,
    roles: () => ['admin', 'roles'] as const,
    roleAssignmentsAll: () => ['admin', 'role-assignments'] as const,
    roleAssignments: (personId: string | null) =>
      ['admin', 'role-assignments', personId] as const,
    personResourcePermissions: (personId: string | null) =>
      ['admin', 'resource-permissions', personId] as const,
    version: () => ['admin', 'version'] as const,
    workers: () => ['admin', 'workers'] as const,
    mattermostChannels: () => ['admin', 'mattermost-channels'] as const,
  },

  // --- Org Placements ---
  orgPlacements: {
    all: ['org-placements'] as const,
    pending: () => ['org-placements', 'pending'] as const,
  },

  // --- Activity ---
  activityFeed: (params?: ActivityFeedParams) => ['activity-feed', params] as const,

  // --- Dashboard ---
  // Keyed by person: the stats are that person's counts, and without the id in
  // the key React Query serves the previous person's cached numbers after a
  // switch and never refetches.
  dashboardStats: (personId: string | undefined) => ['dashboard-stats', personId] as const,

  // --- Graph ---
  graph: {
    all: ['graph'] as const,
    view: (nodeTypes?: string[], limit?: number) => ['graph', nodeTypes, limit] as const,
  },

  // --- Search ---
  search: (query: string, resultTypes?: SearchResultType[]) => ['search', query, resultTypes] as const,

  // --- Mentions ---
  mentions: {
    references: (targetId: string | undefined) => ['mentions', 'references', targetId] as const,
  },

  // --- Mattermost ---
  mattermost: {
    all: ['mattermost'] as const,
    linkStatus: (personId?: string) => ['mattermost', 'link-status', personId] as const,
  },

  // --- Opdrachten ---
  opdrachten: {
    all: ['opdrachten'] as const,
    lists: () => ['opdrachten', 'list'] as const,
    list: (filters?: OpdrachtFilters) => ['opdrachten', 'list', filters] as const,
    detail: (id: string | undefined) => ['opdrachten', 'detail', id] as const,
    summary: (filters?: OpdrachtFilters) => ['opdrachten', 'summary', filters] as const,
  },

  // --- Initiatieven ---
  initiatieven: {
    all: ['initiatieven'] as const,
    lists: () => ['initiatieven', 'list'] as const,
    list: (params?: { search?: string }) => ['initiatieven', 'list', params] as const,
    detail: (id: string | undefined) => ['initiatieven', 'detail', id] as const,
    personen: (id: string | undefined) => ['initiatieven', 'detail', id, 'personen'] as const,
    mattermostChannels: (id: string | undefined) =>
      ['initiatieven', 'detail', id, 'mattermost-channels'] as const,
    debatten: (id: string | undefined) => ['initiatieven', 'detail', id, 'debatten'] as const,
  },

  // --- Mattermost-channels ---
  mattermostChannels: {
    all: ['mattermost-channels'] as const,
    search: (q: string) => ['mattermost-channels', 'search', q] as const,
    forLead: (leadId: string | undefined) =>
      ['leads', 'detail', leadId, 'mattermost-channels'] as const,
  },

  // --- Leads ---
  leads: {
    all: ['leads'] as const,
    lists: () => ['leads', 'list'] as const,
    list: (filters?: LeadFilters) => ['leads', 'list', filters] as const,
    detail: (id: string | null) => ['leads', 'detail', id] as const,
    githubLinks: (leadId: string | null) => ['leads', 'detail', leadId, 'github-links'] as const,
    metrics: () => ['leads', 'metrics'] as const,
  },

  // --- Casussen ---
  casussen: {
    all: ['casussen'] as const,
    lists: () => ['casussen', 'list'] as const,
    list: (initiatiefId: string | undefined) => ['casussen', 'list', initiatiefId] as const,
    detail: (id: string | null) => ['casussen', 'detail', id] as const,
  },
  casusSoorten: {
    all: ['casus-soorten'] as const,
    list: (initiatiefId: string | null) => ['casus-soorten', 'list', initiatiefId] as const,
  },

  // --- Lead-kolommen (per-initiatief funnel-stages) ---
  leadColumns: {
    all: ['lead-columns'] as const,
    list: (initiatiefId: string | undefined) =>
      ['lead-columns', 'list', initiatiefId ?? null] as const,
  },

  // --- Financieel ---
  financieel: {
    all: ['financieel'] as const,
    overzicht: (nodeId: string | undefined) => ['financieel', 'overzicht', nodeId] as const,
    opdrachten: (nodeId: string | undefined) => ['financieel', 'opdrachten', nodeId] as const,
  },

  // --- Samenwerkingsverbanden ---
  samenwerkingsverbanden: {
    all: ['samenwerkingsverbanden'] as const,
    list: (filters?: { search?: string; type?: string; actief?: boolean }) =>
      ['samenwerkingsverbanden', 'list', filters ?? {}] as const,
    detail: (id: string | null) => ['samenwerkingsverbanden', 'detail', id] as const,
    forPerson: (personId: string | null, actief: boolean) =>
      ['samenwerkingsverbanden', 'for-person', personId, { actief }] as const,
  },
} as const;
