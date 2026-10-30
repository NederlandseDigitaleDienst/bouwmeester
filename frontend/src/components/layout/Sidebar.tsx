import { useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import logoImg from '/logo.png?url';
import { useUIStore } from '@/store/ui';
import { useAuth } from '@/contexts/AuthContext';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { usePermissions } from '@/hooks/usePermissions';
import { useManagedEenheden } from '@/hooks/useOrganisatie';
import { formatOrganisatieType } from '@/types';
import { NlddListItemLink, NlddListItemButton } from '@/components/nldd/NlddLink';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';

/** Accessible name per navigation group; each group is its own nav landmark. */
const NAV_GROUP_LABELS: Record<'werk' | 'organisatie' | 'kennis', string> = {
  werk: 'Werk',
  organisatie: 'Organisatie en opdrachten',
  kennis: 'Kennis en zoeken',
};

interface SidebarProps {
  /** Rendered inside the split view's own sheet on narrow screens. */
  mobile?: boolean;
}

interface NavItem {
  to: string;
  /** An nldd-icon name; the cells take a name, not an <Icon> element. */
  icon: string;
  label: string;
  permission?: string;
  /** Items are drawn per group, with a divider between groups. */
  group: 'werk' | 'organisatie' | 'kennis';
}

export function Sidebar({ mobile }: SidebarProps) {
  const { sidebarOpen, toggleSidebar, setMobileSidebarOpen } = useUIStore();
  const { person: authPerson, authenticated, logout, realIsAdmin, viewAsNonAdmin, toggleViewAsNonAdmin } = useAuth();
  const { currentPerson } = useCurrentPerson();
  const { data: managedEenheden } = useManagedEenheden(currentPerson?.id);
  const { hasPermission, hasAnyPermission } = usePermissions();
  const location = useLocation();

  // Inside the sheet the sidebar is always expanded (with labels).
  const expanded = mobile || sidebarOpen;

  const eenheidLabel = useMemo(() => {
    const first = managedEenheden?.[0];
    if (first) return formatOrganisatieType(first.type);
    return 'Eenheid';
  }, [managedEenheden]);

  const navItems = useMemo(() => {
    const items: NavItem[] = [
      { to: '/', icon: 'inbox', label: 'Inbox', group: 'werk' },
      { to: '/corpus', icon: 'network-structure', label: 'Corpus', permission: 'node:read', group: 'werk' },
      { to: '/tasks', icon: 'check-list', label: 'Taken', permission: 'task:read', group: 'werk' },
      {
        to: '/organisatie',
        icon: 'apartment-building',
        label: 'Organisatie',
        permission: 'org:read',
        group: 'organisatie',
      },
      { to: '/eenheid-overzicht', icon: 'users', label: eenheidLabel, permission: 'org:read', group: 'organisatie' },
      { to: '/opdrachten', icon: 'euro-sign', label: 'Opdrachten', permission: 'opdracht:read', group: 'organisatie' },
      // Altijd zichtbaar, zonder recht: de lijst toont alleen initiatieven
      // waar je toegang toe hebt (lidmaatschap, net als de backend), en dit is
      // de enige weg terug naar het overzicht vanuit een initiatief. Met
      // 'lead:read' als voorwaarde zat een lid zonder dat recht vast.
      {
        to: '/initiatieven',
        icon: 'chart-x-y-axis-line',
        label: 'Initiatieven',
        group: 'organisatie',
      },
      {
        to: '/samenwerkingsverbanden',
        icon: 'handshake',
        label: 'Samenwerking',
        permission: 'samenwerkingsverband:read',
        group: 'organisatie',
      },
      { to: '/parlementair', icon: 'file-text', label: 'Kamerstukken', permission: 'node:read', group: 'kennis' },
      { to: '/debatten', icon: 'microphone', label: 'Debatten', permission: 'node:read', group: 'kennis' },
      { to: '/search', icon: 'magnifier', label: 'Zoeken', group: 'kennis' },
      { to: '/docs', icon: 'book', label: 'Handleiding', group: 'kennis' },
    ];
    return items.filter((item) => !item.permission || hasPermission(item.permission));
  }, [eenheidLabel, hasPermission]);

  const bottomNavItems = useMemo(() => {
    const items: NavItem[] = [
      { to: '/instellingen', icon: 'gear', label: 'Instellingen', group: 'werk' },
    ];
    const canAdmin = hasAnyPermission(
      'whitelist:manage',
      'people:manage',
      'config:manage',
      'database:backup',
      'people:assign_role',
      'org:manage',
    );
    const isManager = (authPerson?.managed_eenheden?.length ?? 0) > 0;
    if (hasPermission('audit:read')) {
      items.push({
        to: '/auditlog',
        icon: 'clock-arrow-counter-clockwise',
        label: 'Auditlog',
        group: 'werk',
      });
    }
    if (canAdmin) {
      items.push({ to: '/admin', icon: 'shield', label: 'Beheer', group: 'werk' });
    } else if (isManager) {
      items.push({ to: '/admin?tab=placements', icon: 'shield', label: 'Beheer', group: 'werk' });
    }
    return items;
  }, [authPerson?.managed_eenheden, hasPermission, hasAnyPermission]);

  /** Match the previous NavLink behaviour: exact for "/", prefix for the rest. */
  const isCurrent = (to: string) => {
    const path = to.split('?')[0];
    if (path === '/') return location.pathname === '/';
    return location.pathname === path || location.pathname.startsWith(`${path}/`);
  };

  const closeSheet = () => {
    if (mobile) setMobileSidebarOpen(false);
  };

  /**
   * Eleven items in one strip is a wall of words to scan. Drawing them per
   * group with a line in between keeps the same routes and rights, and only
   * changes how quickly you find one. The design guidelines push further than
   * this, preferring the content itself to carry the navigation.
   */
  const renderGrouped = (items: NavItem[]) => {
    const order: NavItem['group'][] = ['werk', 'organisatie', 'kennis'];
    const groups = order
      .map((group) => items.filter((item) => item.group === group))
      .filter((group) => group.length > 0);

    return groups.map((group, index) => (
      <div key={group[0].to}>
        {index > 0 && <nldd-divider />}
        <nldd-list
          type="navigation"
          appearance="simple"
          dividers="never"
          accessible-label={NAV_GROUP_LABELS[group[0].group]}
        >
          {renderItems(group)}
        </nldd-list>
      </div>
    ));
  };

  const renderCells = (icon: string, label: string) => (
    <>
      <nldd-icon-cell icon={icon} size="20" />
      {/* The cells sit flush against each other: neither the icon cell nor the
          row adds any inline spacing, so without this the label starts exactly
          at the icon's right edge. A spacer cell is how the design system's
          own examples put a gap between two cells. */}
      {expanded ? <nldd-spacer-cell size="12" /> : null}
      {/* Collapsed, the row shows the icon alone. The icon cell has no
          accessible name of its own, so the label stays in the row, hidden
          from sight only; without it a collapsed row, and "Uitloggen" in
          particular, is a control with no name. Never put bare text in a row:
          a cell sets the type scale and color. */}
      <nldd-text-cell text={label} className={expanded ? undefined : 'visually-hidden'} />
    </>
  );

  const renderItems = (items: NavItem[]) =>
    items.map((item) => (
      <NlddListItemLink
        key={item.to}
        to={item.to}
        current={isCurrent(item.to)}
        onNavigate={closeSheet}
      >
        {renderCells(item.icon, item.label)}
      </NlddListItemLink>
    ));

  // Close the sheet first: logging out leaves the page, and the view-as
  // switch changes what the menu itself shows.
  const runAction = (action: () => void) => () => {
    closeSheet();
    action();
  };

  return (
    // Full-height flex column: no nldd-container height="full" equivalent
    // for a column that has to fill the split view's sidebar pane exactly, so
    // the outer shell is plain CSS and everything inside it is nldd.
    <div style={{ display: 'flex', height: '100%', flexDirection: 'column' }}>
      {/* Collapsed the pane is 64px, which does not fit a 32px logo and a 32px
          button beside each other. They stack there instead, so the toggle stays
          reachable — it is the only way back out. */}
      <nldd-container
        layout={expanded ? 'row' : 'stack'}
        gap={expanded ? '12' : '8'}
        vertical-alignment="center"
        horizontal-alignment={expanded ? undefined : 'center'}
        padding-inline={expanded ? '12' : '8'}
        padding-block="12"
        className="shrink-0"
      >
        <nldd-image src={logoImg} decorative width="32" height={32} shape="rounded" className="shrink-0" />
        {expanded && (
          <div style={{ flex: 1, minWidth: 0 }}>
            <nldd-text size="md" weight="bold" className="truncate tracking-tight">
              Bouwmeester
            </nldd-text>
          </div>
        )}
        {!mobile && (
          <NlddIconButton
            icon={sidebarOpen ? 'sidebar-left' : 'sidebar-right'}
            variant="neutral-transparent"
            size="sm"
            accessibleLabel={sidebarOpen ? 'Zijbalk inklappen' : 'Zijbalk uitklappen'}
            onClick={toggleSidebar}
          />
        )}
      </nldd-container>

      {/* `variant="simple"` is a bare strip with no chrome of its own, and an
          interactive row pulls itself 8px outward so the whole widened box is
          one hit area. Both are deliberate, and together they run the rows into
          the pane's edge, so the inset has to come from here: 20px absorbs the
          row's -8px and leaves a 12px gutter.
          Collapsed, the glyph has to sit on the same vertical line as the logo
          and the toggle above it. A 20px glyph in a 64px pane needs 22px of
          padding to be centred, and the row's own -8px outward margin does not
          move its content, so that is the number here rather than the 12px the
          expanded state uses.
          The flex-grow/scroll region has no nldd-container equivalent (no
          primitive for "grow to fill remaining column height and scroll
          independently"), so that part is plain CSS. */}
      <div style={{ flex: 1, overflowY: 'auto', paddingLeft: expanded ? '20px' : '22px', paddingRight: expanded ? '20px' : '22px' }}>
        {renderGrouped(navItems)}
      </div>

      <div className="shrink-0" style={{ paddingLeft: expanded ? '20px' : '22px', paddingRight: expanded ? '20px' : '22px', paddingBottom: '8px' }}>
        <nldd-list
          type="navigation"
          appearance="simple"
          dividers="never"
          accessible-label="Beheer en instellingen"
        >
          {renderItems(bottomNavItems)}
          {/* Actions rather than places, so button rows; a navigation list
              supports those alongside its links. They live here and not in the
              header because they are rarely used and the header toolbar is
              full. */}
          {realIsAdmin && (
            <NlddListItemButton onClick={runAction(toggleViewAsNonAdmin)}>
              {viewAsNonAdmin
                ? renderCells('eye-slash', 'Terug naar beheerweergave')
                : renderCells('eye', 'Bekijk als medewerker')}
            </NlddListItemButton>
          )}
          {authenticated && (
            <NlddListItemButton onClick={runAction(logout)}>
              {renderCells('logout', 'Uitloggen')}
            </NlddListItemButton>
          )}
        </nldd-list>
      </div>
    </div>
  );
}
