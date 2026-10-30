/**
 * Where initiatieven and their leads live in the app.
 *
 * Leads used to have their own page at `/leads`, filtered by initiatief. The
 * initiatief is the thing people open now, and its leads are its first tab,
 * so every link to "the leads" goes through here.
 */

export const INITIATIEVEN_PATH = '/initiatieven';

export type InitiatiefTab =
  | 'leads'
  | 'casussen'
  | 'updates'
  | 'mensen'
  | 'signalen'
  | 'instellingen';

const INITIATIEF_TABS: readonly InitiatiefTab[] = [
  'leads',
  'casussen',
  'updates',
  'mensen',
  'signalen',
  'instellingen',
];

export function isInitiatiefTab(value: string | undefined): value is InitiatiefTab {
  return !!value && (INITIATIEF_TABS as readonly string[]).includes(value);
}

/** The leads tab is the default, so its URL carries no tab segment. */
export function initiatiefPath(id: string, tab: InitiatiefTab = 'leads'): string {
  return tab === 'leads' ? `${INITIATIEVEN_PATH}/${id}` : `${INITIATIEVEN_PATH}/${id}/${tab}`;
}

/**
 * Pages where a dropped file becomes a new lead: the overview and an
 * initiatief's leads tab. Its other tabs are about something else, and a drop
 * there turning into a lead would surprise.
 */
export function isLeadDropPath(pathname: string): boolean {
  const parts = pathname.replace(/\/+$/, '').split('/').filter(Boolean);
  if (parts[0] !== INITIATIEVEN_PATH.slice(1)) return false;
  return parts.length <= 2 || parts[2] === 'leads';
}
