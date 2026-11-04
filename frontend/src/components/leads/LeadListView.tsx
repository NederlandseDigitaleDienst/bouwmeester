import { useCallback, useMemo, useRef, useState } from 'react';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { EmptyState } from '@/components/common/EmptyState';
import { Modal } from '@/components/common/Modal';
import { NlddButton } from '@/components/nldd/NlddButton';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import { useLeads, useMergeLeads, useDeleteLead } from '@/hooks/useLeads';
import { useLeadColumns } from '@/hooks/useLeadColumns';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import { LeadMetricsBar } from './LeadMetricsBar';
import type { Lead, LeadColumn, LeadFilters } from '@/types';
import { isOverdue, formatDateShort, timeAgo } from '@/utils/dates';
import { leadColumnTagColor } from './stageColors';
import { initiatiefTagColor } from '@/components/initiatieven/initiatiefColors';

const SORT_OPTIONS: SelectOption[] = [
  { value: '', label: 'Standaard' },
  { value: 'created_at', label: 'Aangemaakt' },
  { value: 'updated_at', label: 'Laatst gewijzigd' },
  { value: 'next_action_date', label: 'Volgende actie' },
];

interface LeadListViewProps {
  searchQuery?: string;
  initiatiefId: string;
  assigneeId?: string;
  tag?: string;
  nextActionFilter?: string;
  stageFilter?: string;
}

export function LeadListView({
  searchQuery = '',
  initiatiefId,
  assigneeId,
  tag,
  nextActionFilter,
  stageFilter,
}: LeadListViewProps) {
  const [sortBy, setSortBy] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showMergeDialog, setShowMergeDialog] = useState(false);
  const [showBulkDeleteConfirm, setShowBulkDeleteConfirm] = useState(false);

  const filters: LeadFilters = {};
  if (initiatiefId) filters.initiatief_id = initiatiefId;
  if (assigneeId) filters.assignee_id = assigneeId;
  if (tag) filters.tag = tag;
  if (nextActionFilter) filters.next_action_filter = nextActionFilter;
  if (stageFilter) filters.stage = stageFilter;
  if (sortBy) filters.sort_by = sortBy;

  const { data: leads, isLoading } = useLeads(
    Object.keys(filters).length > 0 ? filters : undefined,
  );
  const { columns } = useLeadColumns(initiatiefId);
  const columnsBySlug = useMemo(() => {
    const map = new Map<string, LeadColumn>();
    for (const c of columns) map.set(c.slug, c);
    return map;
  }, [columns]);
  const { openLeadDetail } = useLeadDetail();
  const mergeMutation = useMergeLeads();
  const deleteLead = useDeleteLead();

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const allLeads = leads ?? [];

  const stageIndex = useMemo(() => {
    const map = new Map<string, number>();
    [...columns]
      .sort((a, b) => a.sort_order - b.sort_order)
      .forEach((c, i) => map.set(c.slug, i));
    return map;
  }, [columns]);

  const filteredLeads = useMemo(() => {
    if (!leads) return [];
    if (!searchQuery) return leads;
    const q = searchQuery.toLowerCase();
    return leads.filter((l) =>
      l.title.toLowerCase().includes(q) ||
      (l.organization ?? '').toLowerCase().includes(q) ||
      (l.description ?? '').toLowerCase().includes(q) ||
      (l.assignee?.naam ?? '').toLowerCase().includes(q) ||
      l.tags.some((t) => t.toLowerCase().includes(q))
    );
  }, [leads, searchQuery]);

  const sortedLeads = useMemo(() => {
    return [...filteredLeads].sort((a, b) => {
      const sa = stageIndex.get(a.stage) ?? 99;
      const sb = stageIndex.get(b.stage) ?? 99;
      if (sa !== sb) return sa - sb;
      return a.sort_order - b.sort_order;
    });
  }, [filteredLeads, stageIndex]);

  if (isLoading) {
    return <LoadingSpinner padding="32" />;
  }

  return (
    <nldd-container gap="16">
      <nldd-container layout="row" gap="16" vertical-alignment="center" horizontal-alignment="left">
        <LeadMetricsBar initiatiefId={initiatiefId || undefined} />
        <nldd-container width="fit-content" min-width="176px">
          <CreatableSelect
            value={sortBy}
            onChange={setSortBy}
            options={SORT_OPTIONS}
            placeholder="Standaard"
            searchable={false}
            onClear={sortBy ? () => setSortBy('') : undefined}
          />
        </nldd-container>
      </nldd-container>

      {selectedIds.size > 0 && (
        <nldd-banner
          variant="warning"
          size="sm"
          text={`${selectedIds.size} lead${selectedIds.size !== 1 ? 's' : ''} geselecteerd`}
        >
          <div slot="actions">
            {selectedIds.size === 2 && (
              <NlddButton size="sm" text="Samenvoegen" onClick={() => setShowMergeDialog(true)} />
            )}
            <NlddButton
              size="sm"
              variant="critical-transparent"
              text="Verwijderen"
              onClick={() => setShowBulkDeleteConfirm(true)}
            />
            <NlddButton
              variant="neutral-transparent"
              size="sm"
              text="Deselecteren"
              onClick={() => setSelectedIds(new Set())}
            />
          </div>
        </nldd-banner>
      )}

      {sortedLeads.length === 0 ? (
        <EmptyState
          title="Geen leads gevonden"
          description="Er zijn nog geen leads, of de huidige filters geven geen resultaten."
        />
      ) : (
        <nldd-table
          columns="40px minmax(180px,1.4fr) minmax(120px,1fr) 140px 140px 140px 120px minmax(120px,1fr) 100px"
          sm-columns="40px 1fr"
          md-columns="40px 1.4fr 1fr 140px"
          accessible-label="Leads"
        >
          <nldd-table-row slot="header">
            <nldd-text-cell />
            <nldd-text-cell text="Titel" />
            <nldd-text-cell text="Organisatie" hide-below="md" />
            <nldd-text-cell text="Initiatief" hide-below="lg" />
            <nldd-text-cell text="Fase" hide-below="lg" />
            <nldd-text-cell text="Verantwoordelijke" hide-below="lg" />
            <nldd-text-cell text="Volgende actie" hide-below="lg" />
            <nldd-text-cell text="Tags" hide-below="lg" />
            <nldd-text-cell text="Aangemaakt" hide-below="lg" />
          </nldd-table-row>
          {sortedLeads.map((lead: Lead) => (
            <LeadListRow
              key={lead.id}
              lead={lead}
              column={columnsBySlug.get(lead.stage)}
              selected={selectedIds.has(lead.id)}
              onToggleSelect={() => toggleSelect(lead.id)}
              onOpen={() => openLeadDetail(lead.id)}
            />
          ))}
        </nldd-table>
      )}

      {showMergeDialog && (
        <Modal
          open={showMergeDialog}
          onClose={() => setShowMergeDialog(false)}
          title="Leads samenvoegen"
          size="md"
        >
          <nldd-container gap="16">
            <nldd-text size="sm" color="secondary">
              Kies de lead die je wilt behouden. De andere lead wordt hierin samengevoegd
              (activiteiten, contacten, tags en bijlagen worden overgenomen).
            </nldd-text>
            {Array.from(selectedIds).map((id) => {
              const lead = allLeads.find((l) => l.id === id);
              if (!lead) return null;
              return (
                <MergeCandidateCard
                  key={id}
                  lead={lead}
                  stageName={columnsBySlug.get(lead.stage)?.name ?? lead.stage}
                  disabled={mergeMutation.isPending}
                  onPick={async () => {
                    const otherId = Array.from(selectedIds).find((x) => x !== id)!;
                    await mergeMutation.mutateAsync({ sourceId: otherId, targetId: id });
                    setShowMergeDialog(false);
                    setSelectedIds(new Set());
                  }}
                />
              );
            })}
          </nldd-container>
        </Modal>
      )}

      <ConfirmDialog
        open={showBulkDeleteConfirm}
        onClose={() => setShowBulkDeleteConfirm(false)}
        onConfirm={async () => {
          for (const id of selectedIds) {
            await deleteLead.mutateAsync(id);
          }
          setSelectedIds(new Set());
          setShowBulkDeleteConfirm(false);
        }}
        title="Leads verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
      >
        {selectedIds.size} lead{selectedIds.size !== 1 ? 's' : ''} verwijderen?
      </ConfirmDialog>
    </nldd-container>
  );
}

interface LeadListRowProps {
  lead: Lead;
  column: LeadColumn | undefined;
  selected: boolean;
  onToggleSelect: () => void;
  onOpen: () => void;
}

/**
 * One lead row. The checkbox is its own segment (stopping its click from
 * opening the lead), the rest of the row opens the detail panel.
 */
function LeadListRow({ lead, column, selected, onToggleSelect, onOpen }: LeadListRowProps) {
  const checkboxRef = useRef<HTMLElement>(null);
  const rowRef = useRef<HTMLElement>(null);
  useNlddEvent(checkboxRef, 'change', onToggleSelect);
  useNlddEvent(rowRef, 'click', useCallback(() => onOpen(), [onOpen]));

  const overdue = lead.next_action_date && isOverdue(lead.next_action_date);

  return (
    <nldd-table-row>
      <nldd-text-cell>
        <nldd-checkbox ref={checkboxRef} checked={orUndef(selected)} accessible-label={`Selecteer ${lead.title}`} />
      </nldd-text-cell>
      <nldd-title-cell ref={rowRef} text={lead.title} style={{ cursor: 'pointer' }} />
      <nldd-text-cell text={lead.organisatie_eenheid?.naam ?? lead.organization ?? '-'} hide-below="md" />
      <nldd-text-cell hide-below="lg">
        {lead.initiatief ? (
          <nldd-tag
            text={lead.initiatief.naam}
            color={initiatiefTagColor(lead.initiatief.kleur)}
            size="sm"
          />
        ) : (
          '-'
        )}
      </nldd-text-cell>
      <nldd-text-cell hide-below="lg">
        <nldd-tag text={column?.name ?? lead.stage} color={leadColumnTagColor(column?.color ?? 'neutral')} size="sm" />
      </nldd-text-cell>
      <nldd-text-cell text={lead.assignee?.naam ?? '-'} hide-below="lg" />
      <nldd-text-cell hide-below="lg">
        {lead.next_action_date ? (
          <nldd-container layout="row" gap="4" vertical-alignment="center">
            <nldd-icon icon="calendar" size="16" aria-hidden="true" />
            <nldd-text size="sm" color={overdue ? 'critical' : 'content'} weight={overdue ? 'medium' : 'regular'}>
              {formatDateShort(lead.next_action_date)}
            </nldd-text>
          </nldd-container>
        ) : (
          '-'
        )}
      </nldd-text-cell>
      <nldd-text-cell hide-below="lg">
        <nldd-container layout="wrap" gap="4">
          {lead.tags.slice(0, 3).map((tag) => (
            <nldd-tag key={tag} text={tag} color="neutral" size="sm" />
          ))}
          {lead.tags.length > 3 && (
            <nldd-text size="xs" color="secondary">+{lead.tags.length - 3}</nldd-text>
          )}
        </nldd-container>
      </nldd-text-cell>
      <nldd-text-cell hide-below="lg" title={formatDateShort(lead.created_at)}>
        {timeAgo(lead.created_at)}
      </nldd-text-cell>
    </nldd-table-row>
  );
}

interface MergeCandidateCardProps {
  lead: Lead;
  stageName: string;
  disabled: boolean;
  onPick: () => void;
}

function MergeCandidateCard({ lead, stageName, disabled, onPick }: MergeCandidateCardProps) {
  const ref = useRef<HTMLElement>(null);
  // The guard is here because the element cannot carry one: `nldd-card` has no
  // `disabled` attribute, and `aria-disabled` on it is inert — the button in
  // its shadow root stays operable, so a merge already in flight can be fired
  // again while a screen reader announces the card as disabled. `disabled` is
  // the mutation's pending state.
  useNlddEvent(
    ref,
    'click',
    useCallback(() => {
      if (disabled) return;
      onPick();
    }, [disabled, onPick]),
  );

  return (
    <nldd-card
      ref={ref}
      button
      accessible-label={
        disabled ? `${lead.title} (samenvoegen loopt)` : lead.title
      }
      style={disabled ? { opacity: 0.5, pointerEvents: 'none' } : undefined}
    >
      <nldd-container padding="16">
        <nldd-text-cell
          text={lead.title}
          supporting-text={`${lead.organization ?? 'geen organisatie'} - ${stageName}`}
        />
        <nldd-text size="xs" color="accent">← Deze behouden</nldd-text>
      </nldd-container>
    </nldd-card>
  );
}
