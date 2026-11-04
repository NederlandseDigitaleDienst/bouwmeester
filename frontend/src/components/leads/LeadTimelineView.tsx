import { useState, useMemo, useCallback, useRef } from 'react';
import { format, isToday, isYesterday, subDays, subMonths } from 'date-fns';
import { nl } from 'date-fns/locale';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { NlddButton } from '@/components/nldd/NlddButton';
import { Icon } from '@/components/nldd/Icon';
import { useNlddEvent } from '@/components/nldd/events';
import { LeadMetricsBar } from './LeadMetricsBar';
import { useLeadTimeline } from '@/hooks/useLeads';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import { LeadStage, LEAD_STAGE_LABELS } from '@/types';
import type { LeadTimelineEvent } from '@/types';
import { stageTagColor } from './stageColors';

// -- Period presets --
type PeriodKey = 'week' | 'month' | 'quarter' | 'all';

const PERIOD_OPTIONS: { label: string; value: PeriodKey }[] = [
  { label: 'Afgelopen week', value: 'week' },
  { label: 'Afgelopen maand', value: 'month' },
  { label: 'Afgelopen kwartaal', value: 'quarter' },
  { label: 'Alles', value: 'all' },
];

function periodToDates(period: PeriodKey): { date_from?: string; date_to?: string } {
  const now = new Date();
  switch (period) {
    case 'week':
      return { date_from: subDays(now, 7).toISOString().slice(0, 10) };
    case 'month':
      return { date_from: subMonths(now, 1).toISOString().slice(0, 10) };
    case 'quarter':
      return { date_from: subMonths(now, 3).toISOString().slice(0, 10) };
    case 'all':
      return {};
  }
}

// -- Event type icons (nldd-icon names) --
const EVENT_ICONS: Record<string, string> = {
  meeting: 'calendar-event',
  call: 'at',
  email: 'envelope',
  note: 'message-rectangle-text',
  created: 'plus',
  stage_change: 'arrow-right',
};

function eventIconName(type: string): string {
  return EVENT_ICONS[type] ?? 'sparkles';
}

// -- Date group label --
function formatDateGroupLabel(dateStr: string): string {
  // Parse as noon local time to avoid timezone-induced off-by-one
  const date = new Date(dateStr + 'T12:00:00');
  if (isToday(date)) return 'Vandaag';
  if (isYesterday(date)) return 'Gisteren';
  return format(date, 'd MMMM yyyy', { locale: nl });
}

// -- Group events by date --
function groupEventsByDate(events: LeadTimelineEvent[]): Map<string, LeadTimelineEvent[]> {
  const groups = new Map<string, LeadTimelineEvent[]>();
  for (const event of events) {
    const day = format(new Date(event.timestamp), 'yyyy-MM-dd');
    const existing = groups.get(day);
    if (existing) {
      existing.push(event);
    } else {
      groups.set(day, [event]);
    }
  }
  return groups;
}

// -- Stage badge --
function StageBadge({ stage }: { stage: string }) {
  const label = LEAD_STAGE_LABELS[stage as LeadStage] ?? stage;
  return <nldd-tag text={label} color={stageTagColor(stage)} size="sm" />;
}

// -- Event description --
function EventDescription({ event }: { event: LeadTimelineEvent }) {
  switch (event.event_type) {
    case 'created':
      return (
        <nldd-container layout="row" gap="8" vertical-alignment="center" padding-top="8">
          <nldd-text size="sm" color="secondary">Nieuwe lead aangemaakt</nldd-text>
          <StageBadge stage={event.stage} />
        </nldd-container>
      );

    case 'stage_change':
      return (
        <nldd-container layout="wrap" gap="8" vertical-alignment="center" padding-top="8">
          {event.from_stage && <StageBadge stage={event.from_stage} />}
          <Icon name="arrow-right" size="sm" color="secondary-content" style={{ flexShrink: 0 }} />
          {event.to_stage && <StageBadge stage={event.to_stage} />}
        </nldd-container>
      );

    case 'note':
      return event.content ? (
        <nldd-container padding-top="8">
          <nldd-text size="sm" className="line-clamp-2">
            <RichTextDisplay content={event.content} fallback="" />
          </nldd-text>
        </nldd-container>
      ) : null;

    case 'meeting':
    case 'call':
    case 'email':
      return (
        <nldd-container layout="row" gap="8" padding-top="8">
          <Icon name={eventIconName(event.event_type)} size="sm" color="secondary-content" style={{ flexShrink: 0 }} />
          {event.content ? (
            <nldd-text size="sm" color="secondary" className="line-clamp-2 row-fill">
              <RichTextDisplay content={event.content} fallback="" />
            </nldd-text>
          ) : (
            <nldd-text size="sm" color="secondary" className="line-clamp-2">
              {getActivityLabel(event.event_type)}
            </nldd-text>
          )}
        </nldd-container>
      );

    default:
      return event.content ? (
        <nldd-container padding-top="8">
          <nldd-text size="sm" className="line-clamp-2">
            <RichTextDisplay content={event.content} fallback="" />
          </nldd-text>
        </nldd-container>
      ) : null;
  }
}

function getActivityLabel(type: string): string {
  switch (type) {
    case 'meeting': return 'Meeting vastgelegd';
    case 'call': return 'Telefoongesprek vastgelegd';
    case 'email': return 'E-mail vastgelegd';
    default: return 'Activiteit';
  }
}

// -- Single timeline event row --
//
// This is a feed of distinct events across many leads, not a single entity's
// progress toward a known end, so nldd-step-cell's `status`
// (past/current/future relative to where *you* are) doesn't carry real
// meaning here — every row is simply "past". It still earns its place as the
// per-row dot-and-line lane the design already had: `variant="major"`,
// `status="past"` on every row, `position="between"` throughout (the date
// group headers provide the visual break, so the track itself is one
// continuous line).
function TimelineEventCard({
  event,
  onClickLead,
}: {
  event: LeadTimelineEvent;
  onClickLead: (leadId: string) => void;
}) {
  const time = format(new Date(event.timestamp), 'HH:mm');
  const ref = useRef<HTMLElement>(null);
  const handleClick = useCallback(() => onClickLead(event.lead_id), [onClickLead, event.lead_id]);
  useNlddEvent(ref, 'click', handleClick);

  return (
    <nldd-list-item>
      <nldd-step-cell status="past" level="major" position="between" />
      <nldd-list-item-segment ref={ref} button width="full" accessible-label={event.lead_title}>
        <nldd-container width="full" gap="0">
          <nldd-container layout="row" gap="8" vertical-alignment="top">
            <nldd-container gap="2" width="full">
              <nldd-container layout="row" gap="8" vertical-alignment="center">
                <nldd-text size="xs" color="secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>{time}</nldd-text>
                <Icon name={eventIconName(event.event_type)} size="sm" style={{ opacity: 0.5 }} />
              </nldd-container>
              <nldd-title-cell text={event.lead_title} size={6} />
              {event.organization && (
                <nldd-text size="sm" color="secondary">
                  {event.organization}
                </nldd-text>
              )}
            </nldd-container>
            <StageBadge stage={event.stage} />
          </nldd-container>

          <EventDescription event={event} />

          {(event.actor_naam || event.assignee_naam) && (
            <nldd-container layout="row" gap="12" padding-top="10">
              {event.actor_naam && <nldd-text size="xs" color="secondary">Door {event.actor_naam}</nldd-text>}
              {event.assignee_naam && event.assignee_naam !== event.actor_naam && (
                <nldd-text size="xs" color="secondary">Verantwoordelijk: {event.assignee_naam}</nldd-text>
              )}
            </nldd-container>
          )}
        </nldd-container>
      </nldd-list-item-segment>
    </nldd-list-item>
  );
}

// -- Main timeline view --
interface LeadTimelineViewProps {
  searchQuery?: string;
  initiatiefId: string;
  assigneeId?: string;
  stageFilter?: string;
}

export function LeadTimelineView({
  searchQuery = '',
  initiatiefId,
  assigneeId,
  stageFilter,
}: LeadTimelineViewProps) {
  const [period, setPeriod] = useState<PeriodKey>('month');
  const [displayLimit, setDisplayLimit] = useState(50);

  const { openLeadDetail } = useLeadDetail();

  const dates = periodToDates(period);
  const queryParams = useMemo(
    () => ({
      ...dates,
      ...(stageFilter ? { stage: stageFilter } : {}),
      ...(assigneeId ? { assignee_id: assigneeId } : {}),
      ...(initiatiefId ? { initiatief_id: initiatiefId } : {}),
      limit: 500,
    }),
    [dates.date_from, dates.date_to, stageFilter, assigneeId, initiatiefId],
  );

  const { data, isLoading } = useLeadTimeline(queryParams);

  const events = data?.events ?? [];
  const totalEvents = data?.total ?? 0;

  // Apply client-side search
  const filteredEvents = useMemo(() => {
    if (!searchQuery) return events;
    const q = searchQuery.toLowerCase();
    return events.filter((e) =>
      e.lead_title.toLowerCase().includes(q) ||
      (e.organization ?? '').toLowerCase().includes(q) ||
      (e.actor_naam ?? '').toLowerCase().includes(q) ||
      (e.content ?? '').toLowerCase().includes(q)
    );
  }, [events, searchQuery]);

  const displayedEvents = filteredEvents.slice(0, displayLimit);
  const hasMore = displayedEvents.length < filteredEvents.length;

  const groupedEvents = useMemo(
    () => groupEventsByDate(displayedEvents),
    [displayedEvents],
  );

  return (
    <nldd-container gap="16">
      <LeadMetricsBar initiatiefId={initiatiefId || undefined} />

      {/* Period selector + event count */}
      <nldd-container layout="row" gap="12" vertical-alignment="center">
        <nldd-container layout="row" gap="2">
          {PERIOD_OPTIONS.map((opt) => (
            <NlddButton
              key={opt.value}
              size="sm"
              variant={period === opt.value ? 'neutral-base' : 'neutral-transparent'}
              text={opt.label}
              onClick={() => setPeriod(opt.value)}
            />
          ))}
        </nldd-container>

        {!isLoading && (
          <nldd-text size="xs" color="secondary">
            {totalEvents} {totalEvents === 1 ? 'activiteit' : 'activiteiten'}
          </nldd-text>
        )}
      </nldd-container>

      {/* Timeline */}
      {isLoading ? (
        <LoadingSpinner padding="48" />
      ) : filteredEvents.length === 0 ? (
        <EmptyTimeline />
      ) : (
        <nldd-container gap="8" padding-bottom="32">
          {Array.from(groupedEvents.entries()).map(([dateKey, dayEvents]) => (
            <nldd-container key={dateKey} gap="0">
              {/* Date header stays sticky while its events scroll underneath;
                  nldd-page's sticky-header is a page-level concept and does
                  not apply to an in-flow label inside a scrolling list, so
                  this is plain CSS. */}
              <nldd-text
                size="sm"
                weight="medium"
                color="secondary"
                style={{
                  display: 'block',
                  position: 'sticky',
                  top: 0,
                  zIndex: 20,
                  padding: '10px 0',
                  backgroundColor: 'var(--primitives-color-neutral-0)',
                }}
              >
                {formatDateGroupLabel(dateKey)}
              </nldd-text>

              {/* Events for this date */}
              <nldd-list appearance="simple" dividers="never" accessible-label={`Activiteit op ${formatDateGroupLabel(dateKey)}`}>
                {dayEvents.map((event) => (
                  <TimelineEventCard
                    key={event.id}
                    event={event}
                    onClickLead={openLeadDetail}
                  />
                ))}
              </nldd-list>
            </nldd-container>
          ))}

          {/* Load more */}
          {hasMore && (
            <NlddButton
              text={`Meer laden (${filteredEvents.length - displayLimit} overig)`}
              startIcon="chevron-down"
              variant="secondary"
              size="sm"
              onClick={() => setDisplayLimit((prev) => prev + 50)}
            />
          )}
        </nldd-container>
      )}
    </nldd-container>
  );
}

function EmptyTimeline() {
  return (
    <nldd-inline-dialog
      icon="calendar-event"
      text="Nog geen activiteit"
      supporting-text="Maak een nieuwe lead aan om te beginnen. Alle activiteit verschijnt hier in chronologische volgorde."
      heading-level={2}
    />
  );
}
