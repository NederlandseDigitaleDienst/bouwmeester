import { useState, useMemo } from 'react';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { NlddButton } from '@/components/nldd/NlddButton';
import { LeadCard } from './LeadCard';
import { LeadMetricsBar } from './LeadMetricsBar';
import { LeadIntakeDialog } from './LeadIntakeDialog';
import { useLeads, useMoveLead, useReorderLeads } from '@/hooks/useLeads';
import { useLeadColumns } from '@/hooks/useLeadColumns';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import type { Lead, LeadColumn, LeadFilters } from '@/types';
import { leadColumnTagColor } from './stageColors';

interface LeadKanbanBoardProps {
  searchQuery?: string;
  initiatiefId: string;
  assigneeId?: string;
  tag?: string;
  nextActionFilter?: string;
  stageFilter?: string;
}

export function LeadKanbanBoard({
  searchQuery = '',
  initiatiefId,
  assigneeId,
  tag,
  nextActionFilter,
  stageFilter,
}: LeadKanbanBoardProps) {
  const filters: LeadFilters = {};
  if (initiatiefId) filters.initiatief_id = initiatiefId;
  if (assigneeId) filters.assignee_id = assigneeId;
  if (tag) filters.tag = tag;
  if (nextActionFilter) filters.next_action_filter = nextActionFilter;
  if (stageFilter) filters.stage = stageFilter;

  const { data: leads, isLoading } = useLeads(
    Object.keys(filters).length > 0 ? filters : undefined,
  );
  const { columns, isLoading: columnsLoading } = useLeadColumns(initiatiefId);
  const moveLead = useMoveLead();
  const reorderLeads = useReorderLeads();
  const { openLeadDetail } = useLeadDetail();
  const [dragOverColumn, setDragOverColumn] = useState<string | null>(null);
  const [dragOverSlot, setDragOverSlot] = useState<{
    slug: string;
    index: number;
  } | null>(null);
  const [draggedLeadId, setDraggedLeadId] = useState<string | null>(null);
  const [showIntake, setShowIntake] = useState(false);

  const allLeads = useMemo(() => leads ?? [], [leads]);
  const filteredLeads = useMemo(() => {
    if (!searchQuery) return allLeads;
    const q = searchQuery.toLowerCase();
    return allLeads.filter(
      (l) =>
        l.title.toLowerCase().includes(q) ||
        (l.organization ?? '').toLowerCase().includes(q) ||
        (l.description ?? '').toLowerCase().includes(q) ||
        (l.assignee?.naam ?? '').toLowerCase().includes(q) ||
        l.tags.some((t) => t.toLowerCase().includes(q)),
    );
  }, [allLeads, searchQuery]);

  const visibleColumns = useMemo<LeadColumn[]>(
    () =>
      [...columns]
        .sort((a, b) => a.sort_order - b.sort_order)
        .filter((c) => !stageFilter || c.slug === stageFilter),
    [columns, stageFilter],
  );

  const leadsByStage = useMemo(() => {
    const map: Record<string, Lead[]> = {};
    for (const col of visibleColumns) {
      map[col.slug] = filteredLeads
        .filter((l) => l.stage === col.slug)
        .sort((a, b) => a.sort_order - b.sort_order);
    }
    return map;
  }, [filteredLeads, visibleColumns]);

  if (isLoading || columnsLoading) {
    return <LoadingSpinner padding="32" />;
  }

  const handleDragStart = (e: React.DragEvent, lead: Lead) => {
    e.dataTransfer.setData('text/plain', lead.id);
    e.dataTransfer.effectAllowed = 'move';
    setDraggedLeadId(lead.id);
  };

  const handleDragEnd = () => {
    setDraggedLeadId(null);
    setDragOverColumn(null);
    setDragOverSlot(null);
  };

  // DragOver op een kaart: bepaal boven/onder midden en zet de slot-indicator
  // op de juiste insert-positie.
  const handleCardDragOver = (
    e: React.DragEvent,
    slug: string,
    index: number,
  ) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'move';
    const rect = e.currentTarget.getBoundingClientRect();
    const above = e.clientY < rect.top + rect.height / 2;
    const slotIndex = above ? index : index + 1;
    setDragOverSlot({ slug, index: slotIndex });
    setDragOverColumn(slug);
  };

  // DragOver op de kolom buiten kaarten: drop wordt achteraan geplaatst tenzij
  // een kaart-handler in dezelfde frame al een specifieke slot heeft gezet.
  const handleColumnDragOver = (e: React.DragEvent, slug: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverColumn(slug);
    setDragOverSlot((prev) => {
      if (prev && prev.slug === slug) return prev;
      const length = leadsByStage[slug]?.length ?? 0;
      return { slug, index: length };
    });
  };

  const handleColumnDragLeave = (e: React.DragEvent) => {
    const related = e.relatedTarget as Node | null;
    if (related && e.currentTarget.contains(related)) return;
    setDragOverColumn(null);
    setDragOverSlot(null);
  };

  const reorderWithinStage = (
    targetSlug: string,
    leadId: string,
    targetIndex: number,
  ) => {
    const current = leadsByStage[targetSlug] ?? [];
    const without = current.filter((l) => l.id !== leadId);
    const clampedIndex = Math.max(0, Math.min(targetIndex, without.length));
    const newOrder = [
      ...without.slice(0, clampedIndex).map((l) => l.id),
      leadId,
      ...without.slice(clampedIndex).map((l) => l.id),
    ];
    reorderLeads.mutate({ leadIds: newOrder, stage: targetSlug });
  };

  const performDrop = (
    leadId: string,
    targetSlug: string,
    targetIndex: number,
  ) => {
    const lead = allLeads.find((l) => l.id === leadId);
    if (!lead) return;

    if (lead.stage === targetSlug) {
      reorderWithinStage(targetSlug, leadId, targetIndex);
      return;
    }

    moveLead.mutate(
      { id: leadId, stage: targetSlug },
      {
        onSuccess: () => {
          reorderWithinStage(targetSlug, leadId, targetIndex);
        },
      },
    );
  };

  const handleDrop = (e: React.DragEvent, targetSlug: string) => {
    e.preventDefault();
    const leadId = e.dataTransfer.getData('text/plain');
    const slot = dragOverSlot;
    setDragOverColumn(null);
    setDragOverSlot(null);
    setDraggedLeadId(null);
    if (!leadId) return;

    const targetIndex =
      slot && slot.slug === targetSlug
        ? slot.index
        : (leadsByStage[targetSlug]?.length ?? 0);
    performDrop(leadId, targetSlug, targetIndex);
  };

  return (
    <nldd-container gap="16">
      <LeadMetricsBar initiatiefId={initiatiefId || undefined} />

      {/* The board itself is a plain scroll strip: nldd-container's
          `layout="row"` has no per-child drop-target styling, and every column
          below needs its own onDragOver/onDragLeave/onDrop, drawn with inline
          style because the highlight follows live drag state rather than a
          fixed variant. */}
      <div style={{ display: 'flex', gap: '12px', minHeight: '500px', overflowX: 'auto', paddingBottom: '8px' }}>
        {visibleColumns.map((col) => (
          <div
            key={col.id}
            onDragOver={(e) => handleColumnDragOver(e, col.slug)}
            onDragLeave={handleColumnDragLeave}
            onDrop={(e) => handleDrop(e, col.slug)}
            style={{
              flex: '1 1 0',
              minWidth: '200px',
              width: '320px',
              borderRadius: 'var(--semantics-surfaces-corner-radius)',
              outline: dragOverColumn === col.slug ? '2px solid var(--primitives-color-accent-300)' : 'none',
              outlineOffset: '-2px',
            }}
          >
            {/* A tinted box, not a card: the column is a region that stands
                out from the page, and the lead cards inside sit on it. The
                column's color is its tag's. */}
            <nldd-box background="tinted">
              <nldd-container gap="0">
                <nldd-container layout="row" gap="8" vertical-alignment="center" padding="12" padding-block="10">
                  <nldd-tag text={col.name} color={leadColumnTagColor(col.color)} size="sm" />
                  <nldd-text size="xs" color="secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>
                    <p>{leadsByStage[col.slug]?.length ?? 0}</p>
                  </nldd-text>
                </nldd-container>

                <nldd-container gap="0" padding-inline="8" padding-bottom="8">
                  {(leadsByStage[col.slug] ?? []).length > 0 ? (
                    <>
                      {(leadsByStage[col.slug] ?? []).map((lead, index) => {
                        const indicatorAbove =
                          dragOverSlot?.slug === col.slug &&
                          dragOverSlot.index === index &&
                          draggedLeadId !== lead.id;
                        return (
                          <div key={lead.id}>
                            <div
                              style={{
                                height: '4px',
                                margin: '4px 0',
                                borderRadius: '2px',
                                backgroundColor: indicatorAbove ? 'var(--primitives-color-accent-100)' : 'transparent',
                              }}
                            />
                            <div
                              draggable
                              onDragStart={(e) => handleDragStart(e, lead)}
                              onDragEnd={handleDragEnd}
                              onDragOver={(e) =>
                                handleCardDragOver(e, col.slug, index)
                              }
                              onDrop={(e) => handleDrop(e, col.slug)}
                              style={{ opacity: draggedLeadId === lead.id ? 0.4 : 1 }}
                            >
                              <LeadCard
                                lead={lead}
                                onClick={() => openLeadDetail(lead.id)}
                              />
                            </div>
                          </div>
                        );
                      })}
                      {(() => {
                        const lastIndex = (leadsByStage[col.slug] ?? []).length;
                        const indicatorActive =
                          dragOverSlot?.slug === col.slug &&
                          dragOverSlot.index === lastIndex;
                        return (
                          <div
                            style={{
                              height: '4px',
                              margin: '4px 0',
                              borderRadius: '2px',
                              backgroundColor: indicatorActive ? 'var(--primitives-color-accent-100)' : 'transparent',
                            }}
                          />
                        );
                      })()}
                    </>
                  ) : (
                    <nldd-container padding-block="24">
                      <nldd-text size="xs" color="secondary" horizontal-alignment="center">
                        <p>Sleep leads hierheen</p>
                      </nldd-text>
                    </nldd-container>
                  )}
                </nldd-container>

                <NlddButton
                  text="Nieuwe lead"
                  startIcon="plus"
                  variant="neutral-transparent"
                  size="sm"
                  onClick={() => setShowIntake(true)}
                  width="full"
                />
              </nldd-container>
            </nldd-box>
          </div>
        ))}
      </div>

      <LeadIntakeDialog
        open={showIntake}
        onClose={() => setShowIntake(false)}
        defaultInitiatiefId={initiatiefId}
      />
    </nldd-container>
  );
}
