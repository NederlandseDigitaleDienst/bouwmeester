import { useCallback, useRef, useState, useEffect } from 'react';
import { Navigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { usePermissions } from '@/hooks/usePermissions';
import { useNlddEvent } from '@/components/nldd/events';
import { WhitelistManager } from '@/components/admin/WhitelistManager';
import { DatabaseBackup } from '@/components/admin/DatabaseBackup';
import { AccessRequestManager } from '@/components/admin/AccessRequestManager';
import { PlacementRequestManager } from '@/components/admin/PlacementRequestManager';
import { ConfigManager } from '@/components/admin/ConfigManager';
import { EdgeSchemaManager } from '@/components/admin/EdgeSchemaManager';
import { SharingManager } from '@/components/admin/SharingManager';
import { RoleManager } from '@/components/admin/RoleManager';
import { EenheidBeheerManager } from '@/components/admin/EenheidBeheerManager';
import { ReconciliationManager } from '@/components/admin/ReconciliationManager';
import { SyncStatusManager } from '@/components/admin/SyncStatusManager';
import { SystemInfo } from '@/components/admin/SystemInfo';
type Tab =
  | 'whitelist'
  | 'database'
  | 'requests'
  | 'placements'
  | 'config'
  | 'schema'
  | 'users'
  | 'sharing'
  | 'eenheden'
  | 'reconciliation'
  | 'sync-status'
  | 'system';

export function AdminPage() {
  const { person, oidcConfigured, loading, viewAsNonAdmin } = useAuth();
  const { hasPermission, hasAnyPermission, hasSystemPermission } = usePermissions();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab') as Tab | null;

  const isManager = (person?.managed_eenheden?.length ?? 0) > 0;
  const canAdmin = hasAnyPermission(
    'whitelist:manage',
    'people:manage',
    'config:manage',
    'database:backup',
    'people:assign_role',
    'org:manage',
  );

  const defaultTab: Tab = canAdmin ? 'whitelist' : 'placements';
  const [activeTab, setActiveTab] = useState<Tab>(tabParam || defaultTab);

  useEffect(() => {
    if (tabParam) {
      setActiveTab(tabParam);
    }
  }, [tabParam]);

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab);
    setSearchParams(tab === defaultTab ? {} : { tab });
  };

  // A menu bar, not a tab bar: twelve sections do not fit on one row, and
  // nldd-tab-bar has no overflow of its own, so every label ellipsed away to
  // "Toegan…", "Verzoek…". The menu bar measures what fits and puts the rest
  // behind one overflow button, so the visible labels stay whole.
  //
  // Its items are buttons, so the click comes off the item rather than a
  // `tab-change` event. The listener sits on the bar and reads the id back off
  // the item, which keeps working when items move into the overflow menu.
  const menuBarRef = useRef<HTMLElement>(null);
  useNlddEvent(
    menuBarRef,
    'click',
    useCallback(
      (event: Event) => {
        // Walk the composed path rather than `closest`: the click starts on a
        // button inside the item's shadow root, and `closest` stops at that
        // root instead of crossing back out to the host.
        const item = event
          .composedPath()
          .find(
            (node): node is HTMLElement =>
              node instanceof HTMLElement && node.localName === 'nldd-menu-bar-item',
          );
        const tab = item?.dataset.tabId as Tab | undefined;
        if (tab) handleTabChange(tab);
      },
      // eslint-disable-next-line react-hooks/exhaustive-deps
      [defaultTab],
    ),
  );

  if (loading) {
    return null;
  }

  if (viewAsNonAdmin || (oidcConfigured && (!person || (!canAdmin && !isManager)))) {
    return <Navigate to="/" replace />;
  }

  // Build tabs based on permissions
  const tabs: { id: Tab; label: string }[] = [];

  if (hasPermission('whitelist:manage')) {
    tabs.push({ id: 'whitelist', label: 'Toegangslijst' });
    tabs.push({ id: 'requests', label: 'Verzoeken' });
  }
  if (hasPermission('people:manage') || isManager) {
    tabs.push({ id: 'placements', label: 'Teamverzoeken' });
  }
  if (hasPermission('people:assign_role')) {
    tabs.push({ id: 'users', label: 'Gebruikers' });
  }
  if (hasPermission('org:manage')) {
    tabs.push({ id: 'eenheden', label: 'Eenheden' });
  }
  if (hasPermission('org:manage')) {
    tabs.push({ id: 'sharing', label: 'Delen' });
  }
  if (hasSystemPermission('org:manage')) {
    tabs.push({ id: 'reconciliation', label: 'Reconciliatie' });
  }
  if (hasSystemPermission('org:manage')) {
    tabs.push({ id: 'sync-status', label: 'Sync-status' });
  }
  if (hasPermission('config:manage')) {
    tabs.push({ id: 'config', label: 'Omgevingsvariabelen' });
  }
  if (hasSystemPermission('config:manage')) {
    tabs.push({ id: 'schema', label: 'Relatieschema' });
  }
  if (hasPermission('database:backup')) {
    tabs.push({ id: 'database', label: 'Database' });
  }
  if (hasPermission('config:manage')) {
    tabs.push({ id: 'system', label: 'Systeem' });
  }

  return (
    <nldd-container gap="24">
      {/* Tab bar */}
      <nldd-menu-bar
        ref={menuBarRef}
        accessible-label="Beheeronderdelen"
        overflow-text="Meer"
      >
        {tabs.map((tab) => (
          <nldd-menu-bar-item
            key={tab.id}
            text={tab.label}
            current={activeTab === tab.id ? true : undefined}
            data-tab-id={tab.id}
          />
        ))}
      </nldd-menu-bar>

      {/* Tab content — only render if the tab is in the visible set */}
      {tabs.some((t) => t.id === activeTab) ? (
        <>
          {activeTab === 'whitelist' && <WhitelistManager />}
          {activeTab === 'requests' && <AccessRequestManager />}
          {activeTab === 'placements' && <PlacementRequestManager />}
          {activeTab === 'users' && <RoleManager />}
          {activeTab === 'database' && <DatabaseBackup />}
          {activeTab === 'config' && <ConfigManager />}
          {activeTab === 'schema' && <EdgeSchemaManager />}
          {activeTab === 'sharing' && <SharingManager />}
          {activeTab === 'eenheden' && <EenheidBeheerManager />}
          {activeTab === 'reconciliation' && <ReconciliationManager />}
          {activeTab === 'sync-status' && <SyncStatusManager />}
          {activeTab === 'system' && <SystemInfo />}
        </>
      ) : null}
    </nldd-container>
  );
}
