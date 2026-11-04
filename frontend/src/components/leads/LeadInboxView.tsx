import { useMemo, useState, useRef, useCallback } from 'react';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { EmptyState } from '@/components/common/EmptyState';
import { NlddButton } from '@/components/nldd/NlddButton';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { orUndef, useNlddEvent, useNlddOverlay } from '@/components/nldd/events';
import { useLeads, useUpdateLead, useMoveLead } from '@/hooks/useLeads';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { usePeople } from '@/hooks/usePeople';
import { LeadStage } from '@/types';
import type { Lead, LeadFilters } from '@/types';
import { timeAgo, formatDateShort } from '@/utils/dates';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';

interface LeadInboxViewProps {
  searchQuery?: string;
  initiatiefId: string;
}

type DateGroup = 'vandaag' | 'gisteren' | 'deze_week' | 'ouder';

const DATE_GROUP_LABELS: Record<DateGroup, string> = {
  vandaag: 'Vandaag',
  gisteren: 'Gisteren',
  deze_week: 'Deze week',
  ouder: 'Ouder',
};

function getDateGroup(dateStr: string): DateGroup {
  const date = new Date(dateStr);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);

  if (date >= today) return 'vandaag';
  if (date >= yesterday) return 'gisteren';
  if (date >= weekAgo) return 'deze_week';
  return 'ouder';
}

export function LeadInboxView({
  searchQuery = '',
  initiatiefId,
}: LeadInboxViewProps) {
  const filters: LeadFilters = { stage: LeadStage.INBOX };
  if (initiatiefId) filters.initiatief_id = initiatiefId;

  const { data: leads, isLoading } = useLeads(filters);
  const { data: people } = usePeople();
  const { openLeadDetail } = useLeadDetail();
  const { currentPerson } = useCurrentPerson();
  const updateLead = useUpdateLead();
  const moveLead = useMoveLead();

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [assignDropdownId, setAssignDropdownId] = useState<string | null>(null);

  const filteredLeads = useMemo(() => {
    if (!leads) return [];
    if (!searchQuery) return leads;
    const q = searchQuery.toLowerCase();
    return leads.filter(
      (l) =>
        l.title.toLowerCase().includes(q) ||
        (l.organization ?? '').toLowerCase().includes(q) ||
        (l.description ?? '').toLowerCase().includes(q) ||
        (l.brought_by?.naam ?? '').toLowerCase().includes(q) ||
        l.tags.some((t) => t.toLowerCase().includes(q)),
    );
  }, [leads, searchQuery]);

  const grouped = useMemo(() => {
    const groups: Record<DateGroup, Lead[]> = {
      vandaag: [],
      gisteren: [],
      deze_week: [],
      ouder: [],
    };
    for (const lead of filteredLeads) {
      groups[getDateGroup(lead.created_at)].push(lead);
    }
    return groups;
  }, [filteredLeads]);

  const handleClaim = (lead: Lead) => {
    if (!currentPerson) return;
    updateLead.mutate(
      { id: lead.id, data: { assignee_id: currentPerson.id, stage: LeadStage.VERKENNEN } },
    );
  };

  const handleAssign = (leadId: string, personId: string) => {
    updateLead.mutate(
      { id: leadId, data: { assignee_id: personId, stage: LeadStage.VERKENNEN } },
      { onSuccess: () => setAssignDropdownId(null) },
    );
  };

  const handleKoelkast = (leadId: string) => {
    moveLead.mutate({ id: leadId, stage: LeadStage.KOELKAST });
  };

  const handleBatchClaim = async () => {
    if (!currentPerson) return;
    const ids = [...selectedIds];
    const results = await Promise.allSettled(
      ids.map((id) =>
        updateLead.mutateAsync(
          { id, data: { assignee_id: currentPerson.id, stage: LeadStage.VERKENNEN } },
        ),
      ),
    );
    const failedIds = ids.filter((_, i) => results[i].status === 'rejected');
    setSelectedIds(new Set(failedIds));
  };

  const handleBatchKoelkast = async () => {
    const ids = [...selectedIds];
    const results = await Promise.allSettled(
      ids.map((id) => moveLead.mutateAsync({ id, stage: LeadStage.KOELKAST })),
    );
    const failedIds = ids.filter((_, i) => results[i].status === 'rejected');
    setSelectedIds(new Set(failedIds));
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === filteredLeads.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredLeads.map((l) => l.id)));
    }
  };

  const personOptions = useMemo(
    () =>
      (people ?? [])
        .filter((p) => p.is_active && p.id !== currentPerson?.id)
        .sort((a, b) => a.naam.localeCompare(b.naam))
        .map((p) => ({ value: p.id, label: p.naam })),
    [people, currentPerson],
  );

  if (isLoading) {
    return <LoadingSpinner padding="32" />;
  }

  if (filteredLeads.length === 0) {
    return (
      <EmptyState
        icon="inbox"
        title="Geen nieuwe leads"
        description="Alles is opgepakt! Nieuwe leads verschijnen hier automatisch."
      />
    );
  }

  const groupOrder: DateGroup[] = ['vandaag', 'gisteren', 'deze_week', 'ouder'];

  return (
    <nldd-container gap="8">
      {/* Batch action bar */}
      {selectedIds.size > 0 && (
        <nldd-banner variant="accent" size="sm" text={`${selectedIds.size} geselecteerd`}>
          <div slot="actions">
            <NlddButton
              size="sm"
              text="Oppakken"
              onClick={handleBatchClaim}
              disabled={!currentPerson}
            />
            <NlddButton
              size="sm"
              variant="secondary"
              text="Koelkast"
              onClick={handleBatchKoelkast}
            />
            <NlddButton
              size="sm"
              variant="neutral-transparent"
              text="Deselecteren"
              onClick={() => setSelectedIds(new Set())}
            />
          </div>
        </nldd-banner>
      )}

      {/* Select all */}
      {filteredLeads.length > 1 && selectedIds.size === 0 && (
        <nldd-container padding-inline="12">
          <NlddButton
            size="xs"
            variant="neutral-transparent"
            text={`Alles selecteren (${filteredLeads.length})`}
            onClick={toggleSelectAll}
          />
        </nldd-container>
      )}

      {groupOrder.map((group) => {
        const items = grouped[group];
        if (items.length === 0) return null;

        return (
          <nldd-container key={group} gap="0">
            <nldd-container padding-inline="12" padding-block="6">
              <nldd-title size={6}>
                <h3>{DATE_GROUP_LABELS[group]}</h3>
              </nldd-title>
            </nldd-container>

            <nldd-list appearance="simple" dividers="always" accessible-label={`Leads: ${DATE_GROUP_LABELS[group]}`}>
              {items.map((lead) => (
                <LeadInboxRow
                  key={lead.id}
                  lead={lead}
                  selected={selectedIds.has(lead.id)}
                  onToggleSelect={() => toggleSelect(lead.id)}
                  onOpen={() => openLeadDetail(lead.id)}
                  onClaim={() => handleClaim(lead)}
                  canClaim={!!currentPerson}
                  assignOpen={assignDropdownId === lead.id}
                  onToggleAssign={() =>
                    setAssignDropdownId(assignDropdownId === lead.id ? null : lead.id)
                  }
                  onAssign={(personId) => handleAssign(lead.id, personId)}
                  personOptions={personOptions}
                  onKoelkast={() => handleKoelkast(lead.id)}
                />
              ))}
            </nldd-list>
          </nldd-container>
        );
      })}
    </nldd-container>
  );
}

interface LeadInboxRowProps {
  lead: Lead;
  selected: boolean;
  onToggleSelect: () => void;
  onOpen: () => void;
  onClaim: () => void;
  canClaim: boolean;
  assignOpen: boolean;
  onToggleAssign: () => void;
  onAssign: (personId: string) => void;
  personOptions: { value: string; label: string }[];
  onKoelkast: () => void;
}

/**
 * One inbox row: a checkbox segment, the clickable lead summary, and three
 * action segments. `nldd-list-item` only supports one control type at a time
 * (button/checkbox/href), so a row needing several lives entirely in segments
 * — the item itself carries none of the three.
 */
function LeadInboxRow({
  lead,
  selected,
  onToggleSelect,
  onOpen,
  onClaim,
  canClaim,
  assignOpen,
  onToggleAssign,
  onAssign,
  personOptions,
  onKoelkast,
}: LeadInboxRowProps) {
  const checkboxRef = useRef<HTMLElement>(null);
  const openRef = useRef<HTMLElement>(null);
  const claimRef = useRef<HTMLElement>(null);
  const assignTriggerRef = useRef<HTMLElement>(null);
  const koelkastRef = useRef<HTMLElement>(null);
  const popoverRef = useRef<HTMLElement & { show?: () => void; hide?: () => void }>(null);

  useNlddEvent(checkboxRef, 'change', onToggleSelect);
  useNlddEvent(openRef, 'click', onOpen);
  useNlddEvent(claimRef, 'click', useCallback(() => onClaim(), [onClaim]));
  useNlddEvent(assignTriggerRef, 'click', onToggleAssign);
  useNlddEvent(koelkastRef, 'click', useCallback(() => onKoelkast(), [onKoelkast]));
  // The third argument is what carries a dismissal back up. `close` has
  // `bubbles: false`, so an Escape or a click outside hid the element while
  // the parent still had this lead in `assignDropdownId`. The next click on
  // the trigger then only cleared that state, calling hide() on something
  // already hidden: the popover took two clicks to reopen. The hook swallows
  // the echo of its own hide(), so the toggle is safe to pass here.
  useNlddOverlay(popoverRef, assignOpen, onToggleAssign);

  return (
    <nldd-list-item>
      <nldd-list-item-segment ref={checkboxRef} checkbox checked={orUndef(selected)} accessible-label={`Selecteer ${lead.title}`} />

      <nldd-list-item-segment ref={openRef} button width="full" accessible-label={lead.title}>
        <nldd-text-cell text={lead.title}>
          <span slot="supporting-text">
            <nldd-container gap="4">
              {/* A div around RichTextDisplay, because that renders its own
                  nldd-text or nldd-rich-text, so there is no single element
                  of ours to put `line-clamp-2` on. Where the text is ours,
                  the class goes on nldd-text itself (LeadCard, NodeCard). */}
              {lead.description && (
                <div
                  className="line-clamp-2"
                  style={{
                    font: 'var(--primitives-font-body-xs-regular-snug)',
                    color: 'var(--semantics-content-secondary-color)',
                  }}
                >
                  <RichTextDisplay content={lead.description} fallback="" />
                </div>
              )}

              <nldd-container layout="wrap" gap="4">
                {lead.brought_by && (
                  <nldd-text size="xs" color="secondary">via {lead.brought_by.naam}</nldd-text>
                )}
                {lead.organization && (
                  <nldd-text size="xs" color="secondary">
                    {lead.organisatie_eenheid?.naam ?? lead.organization}
                  </nldd-text>
                )}
                {lead.contact_names.length > 0 && (
                  <div className="hug hug-gap-2 hug-truncate" title={lead.contact_names.join(', ')}>
                    <nldd-icon icon="users" size="16" aria-hidden="true" />
                    <nldd-text size="xs" color="secondary">
                      {lead.contact_names[0]}
                      {lead.contact_names.length > 1 && ` +${lead.contact_names.length - 1}`}
                    </nldd-text>
                  </div>
                )}
                {lead.next_action_date && (
                  <div className="hug hug-gap-2">
                    <nldd-icon icon="calendar" size="16" aria-hidden="true" />
                    <nldd-text size="xs" color="secondary">{formatDateShort(lead.next_action_date)}</nldd-text>
                  </div>
                )}
                {lead.attachment_count > 0 && (
                  <div className="hug hug-gap-2">
                    <nldd-icon icon="paperclip" size="16" aria-hidden="true" />
                    <nldd-text size="xs" color="secondary">{lead.attachment_count}</nldd-text>
                  </div>
                )}
                <nldd-text size="xs" color="secondary">{timeAgo(lead.created_at)}</nldd-text>
              </nldd-container>

              {lead.tags.length > 0 && (
                <nldd-container layout="wrap" gap="4">
                  {lead.tags.slice(0, 4).map((tag) => (
                    <nldd-tag key={tag} text={tag} color="neutral" size="sm" />
                  ))}
                  {lead.tags.length > 4 && (
                    <nldd-text size="xs" color="secondary">+{lead.tags.length - 4}</nldd-text>
                  )}
                </nldd-container>
              )}
            </nldd-container>
          </span>
        </nldd-text-cell>
      </nldd-list-item-segment>

      <nldd-list-item-segment ref={claimRef} button disabled={orUndef(!canClaim)} accessible-label="Zelf oppakken">
        Oppakken
      </nldd-list-item-segment>

      <nldd-list-item-segment
        ref={assignTriggerRef}
        button
        id={`assign-trigger-${lead.id}`}
        accessible-label="Toewijzen aan iemand anders"
      >
        <nldd-icon icon="person-badge-plus" size="16" aria-hidden="true" />
        <nldd-icon icon="chevron-down" size="16" aria-hidden="true" />
      </nldd-list-item-segment>
      {/* Popovers render at the document root: this one sits after the row
          rather than nested in it, anchored by id so it never gets sized by
          the row's own layout. */}
      <nldd-popover
        ref={popoverRef}
        anchor={`assign-trigger-${lead.id}`}
        accessible-label="Toewijzen aan iemand anders"
        width="280px"
      >
        <CreatableSelect
          value=""
          onChange={onAssign}
          options={personOptions}
          placeholder="Zoek een persoon..."
        />
      </nldd-popover>

      <nldd-list-item-segment ref={koelkastRef} button accessible-label="Naar koelkast">
        <nldd-icon icon="snowflake" size="16" aria-hidden="true" />
      </nldd-list-item-segment>
    </nldd-list-item>
  );
}
