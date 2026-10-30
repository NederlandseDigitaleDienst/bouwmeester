import { useCallback, useRef } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { useNlddEvent } from '@/components/nldd/events';
import { useInitiatief } from '@/hooks/useInitiatieven';
import { InitiatiefLeads } from '@/components/initiatieven/InitiatiefLeads';
import { InitiatiefCasussen } from '@/components/casussen/InitiatiefCasussen';
import { InitiatiefBacklog } from '@/components/casussen/InitiatiefBacklog';
import { InitiatiefUpdates } from '@/components/initiatieven/InitiatiefUpdates';
import { InitiatiefMensen } from '@/components/initiatieven/InitiatiefMensen';
import { InitiatiefSignalen } from '@/components/initiatieven/InitiatiefSignalen';
import { InitiatiefInstellingen } from '@/components/initiatieven/InitiatiefInstellingen';
import {
  initiatiefPath,
  isInitiatiefTab,
  type InitiatiefTab,
} from '@/utils/initiatiefRoutes';
import type { InitiatiefDetail } from '@/types';

const TAB_LABELS: Record<InitiatiefTab, string> = {
  leads: 'Leads',
  casussen: 'Casussen',
  backlog: 'Backlog',
  updates: 'Updates',
  mensen: 'Mensen',
  signalen: 'Signalen',
  instellingen: 'Instellingen',
};

/**
 * The tabs this person gets. Ordered by how often they are used: the leads
 * daily, updates weekly, people and signals now and then, settings once.
 * A viewer changes nothing, so has no settings tab.
 */
function visibleTabs(initiatief: InitiatiefDetail): InitiatiefTab[] {
  const canEdit =
    initiatief.access_level === 'eigenaar' || initiatief.access_level === 'contributor';
  const tabs: InitiatiefTab[] = ['leads', 'casussen', 'backlog', 'updates', 'mensen', 'signalen'];
  if (canEdit) tabs.push('instellingen');
  return tabs;
}

/**
 * One initiatief, with its work split over tabs. This replaces the settings
 * modal on the old leads page, which had grown to hold everything but the
 * leads themselves. The tab is part of the path, so each one can be linked.
 */
export function InitiatiefPage() {
  const { id, tab } = useParams<{ id: string; tab?: string }>();
  const { data: initiatief, isLoading, isError } = useInitiatief(id);

  if (isLoading) {
    return (
      <nldd-container layout="row" horizontal-alignment="center" padding="48">
        <LoadingSpinner />
      </nldd-container>
    );
  }
  if (!id || isError || !initiatief) {
    return (
      <nldd-container padding="48" horizontal-alignment="center">
        <nldd-text size="sm" color="secondary" horizontal-alignment="center">
          Initiatief niet gevonden, of je hebt er geen toegang toe.
        </nldd-text>
      </nldd-container>
    );
  }

  const tabs = visibleTabs(initiatief);
  const activeTab: InitiatiefTab | null = tab === undefined ? 'leads' : isInitiatiefTab(tab) ? tab : null;
  if (!activeTab || !tabs.includes(activeTab)) {
    return <Navigate to={initiatiefPath(id)} replace />;
  }

  // Twee lagen: waar (de tabs) en wat (de inhoud van de tab). De naam en de
  // publieke link staan in de kop van de app ("Initiatieven › naam"); terug
  // naar het overzicht gaat via Initiatieven in de zijbalk, en de beschrijving
  // staat bij de instellingen.
  return (
    <nldd-container gap="24">
      <InitiatiefTabBar initiatiefId={id} tabs={tabs} activeTab={activeTab} />

      {/* Keyed on the initiatief, so switching between two of them does not
          carry a half-typed form or a filter from one into the other. */}
      <div key={initiatief.id}>
        {activeTab === 'leads' && <InitiatiefLeads initiatiefId={initiatief.id} />}
        {activeTab === 'casussen' && <InitiatiefCasussen initiatiefId={initiatief.id} />}
        {activeTab === 'backlog' && <InitiatiefBacklog initiatiefId={initiatief.id} />}
        {activeTab === 'updates' && <TabBody><InitiatiefUpdates initiatief={initiatief} /></TabBody>}
        {activeTab === 'mensen' && <TabBody><InitiatiefMensen initiatief={initiatief} /></TabBody>}
        {activeTab === 'signalen' && <TabBody><InitiatiefSignalen initiatief={initiatief} /></TabBody>}
        {activeTab === 'instellingen' && <TabBody><InitiatiefInstellingen initiatief={initiatief} /></TabBody>}
      </div>
    </nldd-container>
  );
}

/**
 * The section tabs. Their own component, so the `tabchange` listener binds
 * when the bar mounts: `useNlddEvent` binds once, and on the page itself it
 * ran while the loading spinner was still showing, found no bar, and never
 * bound at all. The tabs then lit up on click and changed nothing.
 */
function InitiatiefTabBar({
  initiatiefId,
  tabs,
  activeTab,
}: {
  initiatiefId: string;
  tabs: InitiatiefTab[];
  activeTab: InitiatiefTab;
}) {
  const navigate = useNavigate();
  const ref = useRef<HTMLElement>(null);
  const handleTabChange = useCallback(
    (event: Event) => {
      const item = (event as CustomEvent<{ item?: HTMLElement }>).detail?.item;
      const next = item?.dataset.tabId;
      if (isInitiatiefTab(next)) navigate(initiatiefPath(initiatiefId, next));
    },
    [initiatiefId, navigate],
  );
  useNlddEvent(ref, 'tabchange', handleTabChange);

  return (
    <nldd-tab-bar ref={ref} variant="text" accessible-label="Onderdelen van het initiatief">
      {tabs.map((t) => (
        <nldd-tab-bar-item
          key={t}
          text={TAB_LABELS[t]}
          data-tab-id={t}
          current={activeTab === t ? true : undefined}
        />
      ))}
    </nldd-tab-bar>
  );
}

/**
 * The leads need the full width for the board; the other tabs are forms and
 * lists, which read badly stretched across a wide screen.
 */
function TabBody({ children }: { children: React.ReactNode }) {
  return (
    <nldd-container max-width="768px" padding-top="8">
      {children}
    </nldd-container>
  );
}
