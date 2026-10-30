import { useCallback, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from '@/components/common/Card';
import { InboxList } from '@/components/inbox/InboxList';
import { MessageThread } from '@/components/inbox/MessageThread';
import { EmptyState } from '@/components/common/EmptyState';
import { useNlddEvent } from '@/components/nldd/events';
import { useNotifications, useDashboardStats, useMarkAllNotificationsRead, useMarkNotificationRead } from '@/hooks/useNotifications';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { useAuth } from '@/contexts/AuthContext';
import { useDismissOnboardingFeature } from '@/hooks/useOnboarding';
import { useManagedEenheden } from '@/hooks/useOrganisatie';
import { useEenheidOverview } from '@/hooks/useTasks';
import { formatCurrencyCompact } from '@/utils/format';
import type { InboxItem } from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

const NOTIFICATION_TYPE_MAP: Record<string, string> = {
  task_assigned: 'task',
  task_reassigned: 'task',
  task_completed: 'task',
  task_overdue: 'task',
  edge_created: 'node',
  node_updated: 'node',
  stakeholder_added: 'notification',
  stakeholder_role_changed: 'notification',
  coverage_needed: 'notification',
  politieke_input_imported: 'notification',
  mention: 'notification',
  direct_message: 'message',
  agent_prompt: 'message',
  opdracht_created: 'notification',
  opdracht_status_changed: 'notification',
};

const PERSON_LEVEL_TYPES = new Set(['afdeling', 'dienst', 'bureau', 'cluster', 'team']);

function GettingStartedCard() {
  const navigate = useNavigate();
  const { person, refreshAuthStatus } = useAuth();
  const dismissMutation = useDismissOnboardingFeature();
  const bannerRef = useRef<HTMLElement>(null);

  const showIntro = person?.onboarding_features?.some(
    (f) => f.key === 'intro_handleiding',
  );

  const handleDismiss = useCallback(async () => {
    await dismissMutation.mutateAsync({ featureKey: 'intro_handleiding', permanent: true });
    await refreshAuthStatus();
  }, [dismissMutation, refreshAuthStatus]);
  useNlddEvent(bannerRef, 'dismiss', handleDismiss);

  if (!showIntro) return null;

  return (
    <nldd-banner
      ref={bannerRef}
      variant="accent"
      icon="book"
      text="Nieuw hier?"
      supporting-text="Lees de introductie om te ontdekken wat je met Bouwmeester kunt doen en hoe je snel op weg komt."
      dismissible
    >
      <div slot="actions">
        <NlddButton variant="primary" size="sm" onClick={() => navigate('/docs?tab=introductie')} text="Ontdek Bouwmeester" />
      </div>
    </nldd-banner>
  );
}

export function InboxPage() {
  const navigate = useNavigate();
  const [openThreadId, setOpenThreadId] = useState<string | null>(null);

  const { currentPerson } = useCurrentPerson();
  const { data: notifications } = useNotifications();
  const { data: stats } = useDashboardStats();
  const markAllRead = useMarkAllNotificationsRead();
  const markRead = useMarkNotificationRead();
  const { data: managedEenheden } = useManagedEenheden(currentPerson?.id);
  const managedEenheid = managedEenheden?.[0] ?? null;
  const managedEenheidId = managedEenheid?.id ?? null;
  const { data: overview } = useEenheidOverview(managedEenheidId);

  const visibleUnassignedCount = overview
    ? (overview.unassigned_no_unit_count ?? 0) +
      (PERSON_LEVEL_TYPES.has(overview.eenheid_type) ? (overview.unassigned_no_person_count ?? 0) : 0)
    : 0;

  const inboxItems: InboxItem[] = (notifications ?? []).map((n) => ({
    id: n.id,
    type: NOTIFICATION_TYPE_MAP[n.type] ?? 'notification',
    notification_type: n.type,
    title: n.title,
    description: n.message,
    node_id: n.related_node_id,
    task_id: n.related_task_id,
    lead_id: n.related_lead_id,
    sender_name: n.sender_name,
    reply_count: n.reply_count,
    created_at: n.created_at,
    read: n.is_read,
  }));

  const unreadCount = inboxItems.filter((item) => !item.read).length;
  const hasUnread = unreadCount > 0;

  return (
    <nldd-simple-section width="960px" horizontal-alignment="center">
      <nldd-container gap="24">
        {/* Welcome banner. The gradient hero has no nldd equivalent (no
            component paints a two-stop brand gradient), so it stays a plain
            styled div. The colors are the design system's own accent step,
            never a literal swatch. */}
        <div
          style={{
            borderRadius: '16px',
            padding: '24px',
            color: 'white',
            background:
              'linear-gradient(to bottom right, var(--primitives-color-lintblauw-900), var(--primitives-color-lintblauw-700))',
          }}
        >
          {/* A greeting, not a section, so a <span> rather than a heading: the
              page already has its h1 in the title bar, and a second heading
              here, set larger than that h1, put the loudest text on the page
              outside the document outline entirely.

              It has to be an element, not bare text. The component styles its
              title through `::slotted(:not([slot]))`, which only matches
              elements, so a loose text node drops to the surrounding 18px and
              the banner stops reading as a banner. */}
          <nldd-title size={5} color="inherit">
            <span>Welkom bij Bouwmeester</span>
          </nldd-title>
          <nldd-text color="inherit" style={{ opacity: 0.7 }}>
            Je werkplek voor beleid, taken en samenwerking.
          </nldd-text>
        </div>

        {/* Getting started card for new users */}
        <GettingStartedCard />

        {/* Quick stats */}
        <nldd-collection layout="grid" item-min-width="200px" gap="16">
          <Card actionLabel="Corpus nodes bekijken" onClick={() => navigate('/corpus')}>
            <nldd-container layout="row" gap="12" vertical-alignment="center">
              <nldd-icon icon="network-structure" size="40" color="lintblauw" box />
              <nldd-container gap="0">
                <nldd-text size="lg" weight="bold">{stats?.corpus_node_count ?? '-'}</nldd-text>
                <nldd-text size="xs" color="secondary">Corpus nodes</nldd-text>
              </nldd-container>
            </nldd-container>
          </Card>

          <Card actionLabel="Open taken bekijken" onClick={() => navigate('/tasks')}>
            <nldd-container layout="row" gap="12" vertical-alignment="center">
              <nldd-icon icon="check-list" size="40" color="geel" box />
              <nldd-container gap="0">
                <nldd-text size="lg" weight="bold">{stats?.open_task_count ?? '-'}</nldd-text>
                <nldd-text size="xs" color="secondary">Open taken</nldd-text>
              </nldd-container>
            </nldd-container>
          </Card>

          <Card actionLabel="Achterstallige taken bekijken" onClick={() => navigate('/tasks')}>
            <nldd-container layout="row" gap="12" vertical-alignment="center">
              <nldd-icon icon="chart-x-y-axis-line" size="40" color="robijnrood" box />
              <nldd-container gap="0">
                <nldd-text size="lg" weight="bold">{stats?.overdue_task_count ?? '-'}</nldd-text>
                <nldd-text size="xs" color="secondary">Achterstallig</nldd-text>
              </nldd-container>
            </nldd-container>
          </Card>

          <Card
            actionLabel="Actief budget bekijken"
            onClick={() => {
              const params = currentPerson?.id ? `?verantwoordelijke_id=${currentPerson.id}` : '';
              navigate(`/opdrachten${params}`);
            }}
          >
            <nldd-container layout="row" gap="12" vertical-alignment="center">
              <nldd-icon icon="euro-sign" size="40" color="mosgroen" box />
              <nldd-container gap="0">
                <nldd-text size="lg" weight="bold" style={{ whiteSpace: 'nowrap' }}>
                  {stats?.active_opdracht_budget != null ? formatCurrencyCompact(stats.active_opdracht_budget) : '-'}
                </nldd-text>
                <nldd-text size="xs" color="secondary">Actief budget</nldd-text>
              </nldd-container>
            </nldd-container>
          </Card>
        </nldd-collection>

        {/* Manager stats card */}
        {managedEenheidId && visibleUnassignedCount > 0 && (
          <Card actionLabel="Onverdeelde taken verdelen" onClick={() => navigate('/eenheid-overzicht')}>
            <nldd-container layout="row" gap="12" vertical-alignment="center">
              <nldd-icon icon="users" size="40" color="violet" box />
              <nldd-container gap="0" width="full">
                <nldd-text size="sm" weight="medium">
                  {visibleUnassignedCount} onverdeelde {visibleUnassignedCount === 1 ? 'taak' : 'taken'}
                </nldd-text>
                <nldd-text size="xs" color="secondary">
                  In jouw eenheid - klik om te verdelen
                </nldd-text>
              </nldd-container>
            </nldd-container>
          </Card>
        )}

        {/* Inbox section */}
        <nldd-container gap="12">
          <nldd-container layout="row" width="full" gap="8" vertical-alignment="center">
            {/* The heading leads the row and the action trails it, so the
                heading takes the leftover space rather than the row pushing
                everything to one side.

                Sizes measured on the page: 3 is 32px, 4 is 26px, 5 is 20px,
                6 is 18px, and the title bar's h1 is 20px. A section of the
                page sits below that h1, so 6; at 4 it rendered larger than the
                heading naming the whole page. */}
            <nldd-container
              width="fit-content"
              className="row-fill"
              layout="row"
              gap="8"
              vertical-alignment="center"
            >
              <nldd-title size={6}><h2>Meldingen</h2></nldd-title>
              {/* The count belongs to the heading, not to a second label under
                  it. Unread is the number that asks for something; the total
                  is visible by scrolling. */}
              {hasUnread && (
                <nldd-text size="sm" color="secondary">
                  {unreadCount} ongelezen
                </nldd-text>
              )}
            </nldd-container>
            {hasUnread && currentPerson?.id && (
              <NlddButton variant="neutral-transparent" size="sm" startIcon="check-list" onClick={() => markAllRead.mutate()} text="Alles gelezen" />
            )}
          </nldd-container>

          {inboxItems.length > 0 ? (
            <InboxList items={inboxItems} onOpenThread={setOpenThreadId} onMarkRead={(id) => markRead.mutate(id)} />
          ) : (
            <EmptyState
              icon="inbox"
              title="Geen nieuwe meldingen"
              description="Toewijzingen en vermeldingen komen hier binnen."
              action={
                /* One suggestion, not two equal ones. A centred dialog lays its
                   actions out stacked and full-width, so a second button here
                   became a second 480px bar competing with the first for a
                   choice nobody is being asked to make. Taken has its own place
                   in the sidebar. */
                <NlddButton variant="secondary" onClick={() => navigate('/corpus')} text="Bekijk corpus" />
              }
            />
          )}
        </nldd-container>

        {/* Thread modal */}
        {openThreadId && (
          <MessageThread
            notificationId={openThreadId}
            onClose={() => setOpenThreadId(null)}
          />
        )}
      </nldd-container>
    </nldd-simple-section>
  );
}
