import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Input } from '@/components/common/Input';
import { ViewToggle } from '@/components/common/ViewToggle';
import type { ViewToggleOption } from '@/components/common/ViewToggle';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { useDebounce } from '@/hooks/useDebounce';
import { usePeople } from '@/hooks/usePeople';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { LeadKanbanBoard } from '@/components/leads/LeadKanbanBoard';
import { LeadListView } from '@/components/leads/LeadListView';
import { LeadGraphView } from '@/components/leads/LeadGraphView';
import { LeadTimelineView } from '@/components/leads/LeadTimelineView';
import { LeadInboxView } from '@/components/leads/LeadInboxView';
import { LeadIntakeDialog } from '@/components/leads/LeadIntakeDialog';
import { LeadStage, LEAD_STAGE_LABELS } from '@/types';
import { useGlobalFileDropContext } from '@/hooks/useGlobalFileDropContext';
import { NlddButton } from '@/components/nldd/NlddButton';

type LeadViewMode = 'inbox' | 'kanban' | 'list' | 'graph' | 'timeline';

// String icon names: the icon-only toggle draws them through the item's own
// `icon` attribute and uses the label as tooltip and accessible name.
const VIEW_OPTIONS: ViewToggleOption<LeadViewMode>[] = [
  { value: 'inbox', label: 'Inbox', icon: 'inbox' },
  { value: 'kanban', label: 'Bord', icon: 'columns-3' },
  { value: 'list', label: 'Lijst', icon: 'square-grid-2x2' },
  { value: 'timeline', label: 'Tijdlijn', icon: 'clock' },
  { value: 'graph', label: 'Netwerk', icon: 'git-fork' },
];

const VIEW_MODES: readonly LeadViewMode[] = ['inbox', 'kanban', 'list', 'graph', 'timeline'];

const NEXT_ACTION_OPTIONS: SelectOption[] = [
  { value: '', label: 'Alle acties' },
  { value: 'overdue', label: 'Achterstallig' },
  { value: 'today', label: 'Vandaag' },
  { value: 'this_week', label: 'Deze week' },
];

const STAGE_OPTIONS: SelectOption[] = [
  { value: '', label: 'Alle fases' },
  ...Object.values(LeadStage).map((s) => ({
    value: s,
    label: LEAD_STAGE_LABELS[s],
  })),
];

/** The leads search field: `nldd-search-field` with its `input` event bridged to React. */
function LeadsSearchField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));
  return (
    <nldd-search-field
      ref={ref}
      value={value}
      placeholder="Zoek in leads..."
      accessible-label="Zoek in leads"
    />
  );
}

/**
 * The "Leads" tab of an initiatief: the funnel in five views, with the
 * filters that apply to the current one. This was the leads page, minus the
 * row of initiatief pills: the initiatief is fixed by the page it sits on.
 */
export function InitiatiefLeads({ initiatiefId }: { initiatiefId: string }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const viewParam = searchParams.get('view') as LeadViewMode | null;
  const viewMode: LeadViewMode = viewParam && VIEW_MODES.includes(viewParam) ? viewParam : 'inbox';

  const [showIntake, setShowIntake] = useState(false);
  const { subscribe } = useGlobalFileDropContext();
  const [droppedFiles, setDroppedFiles] = useState<File[]>([]);

  // Subscribe to global file drops while this tab is mounted
  useEffect(() => {
    return subscribe((files) => {
      setDroppedFiles(files);
      setShowIntake(true);
    });
  }, [subscribe]);

  // Search
  const [searchInput, setSearchInput] = useState('');
  const searchQuery = useDebounce(searchInput, 200);

  // Shared filters
  const [filterAssignee, setFilterAssignee] = useState('');
  const [filterTag, setFilterTag] = useState('');
  const [nextActionFilter, setNextActionFilter] = useState('');
  const [filterStage, setFilterStage] = useState('');

  // People for assignee filter
  const { data: people } = usePeople();
  const { currentPerson } = useCurrentPerson();

  const setViewMode = useCallback(
    (mode: LeadViewMode) => {
      setSearchParams((prev) => {
        if (mode === 'inbox') {
          prev.delete('view');
        } else {
          prev.set('view', mode);
        }
        return prev;
      }, { replace: true });
    },
    [setSearchParams],
  );

  // Filters applicable per view: inbox uses only search; kanban+list support all; timeline lacks tag/next_action; graph only has stage
  const supportsAssignee = viewMode !== 'graph' && viewMode !== 'inbox';
  const supportsTag = viewMode === 'kanban' || viewMode === 'list';
  const supportsNextAction = viewMode === 'kanban' || viewMode === 'list';
  const supportsStage = viewMode !== 'inbox';

  const hasActiveFilters = filterAssignee || filterTag || nextActionFilter || filterStage;

  const clearFilters = () => {
    setFilterAssignee('');
    setFilterTag('');
    setNextActionFilter('');
    setFilterStage('');
  };

  return (
    <nldd-container gap="16">
      <nldd-toolbar accessible-label="Leadacties">
        {/* Search and filters share one fluid item, so on a wide screen they
            sit on the same line as the view switcher and the add button, and
            only wrap when the room runs out. `min-width` is what makes a
            toolbar item fluid; a percentage lets it give way to the end items
            instead of pushing them into the overflow menu. Every field gets a
            fixed width: a container without one takes the full row, which is
            how the tag filter used to claim a line of its own. */}
        <nldd-toolbar-item slot="start" priority={1} min-width="60%">
          <nldd-container layout="wrap" gap="8" vertical-alignment="center">
            <nldd-container width="208px">
              <LeadsSearchField value={searchInput} onChange={setSearchInput} />
            </nldd-container>

            {supportsAssignee && (
              <nldd-container width="176px">
                <CreatableSelect
                  value={filterAssignee}
                  onChange={setFilterAssignee}
                  options={[
                    { value: '', label: 'Alle personen' },
                    ...(currentPerson
                      ? [{ value: currentPerson.id, label: `Mijn leads (${currentPerson.naam})` }]
                      : []),
                    ...(people
                      ?.filter((p) => p.is_active && p.id !== currentPerson?.id)
                      .map((p) => ({ value: p.id, label: p.naam, description: p.functie ?? undefined })) ?? []),
                  ]}
                  placeholder="Alle personen"
                  onClear={filterAssignee ? () => setFilterAssignee('') : undefined}
                />
              </nldd-container>
            )}

            {supportsTag && (
              <nldd-container layout="row" gap="4" width="160px" vertical-alignment="center">
                <nldd-container width="full">
                  <Input
                    value={filterTag}
                    onChange={(e) => setFilterTag(e.target.value)}
                    placeholder="Filter op tag"
                  />
                </nldd-container>
                {filterTag && (
                  <NlddIconButton
                    icon="close"
                    accessibleLabel="Tag-filter wissen"
                    variant="neutral-transparent"
                    size="sm"
                    onClick={() => setFilterTag('')}
                  />
                )}
              </nldd-container>
            )}

            {supportsNextAction && (
              <nldd-container width="144px">
                <CreatableSelect
                  value={nextActionFilter}
                  onChange={setNextActionFilter}
                  options={NEXT_ACTION_OPTIONS}
                  placeholder="Alle acties"
                  searchable={false}
                  onClear={nextActionFilter ? () => setNextActionFilter('') : undefined}
                />
              </nldd-container>
            )}

            {supportsStage && (
              <nldd-container width="144px">
                <CreatableSelect
                  value={filterStage}
                  onChange={setFilterStage}
                  options={STAGE_OPTIONS}
                  placeholder="Alle fases"
                  searchable={false}
                  onClear={filterStage ? () => setFilterStage('') : undefined}
                />
              </nldd-container>
            )}

            {hasActiveFilters && (
              <NlddButton variant="neutral-transparent" size="sm" onClick={clearFilters} text="Wissen" />
            )}
          </nldd-container>
        </nldd-toolbar-item>
        <nldd-toolbar-item slot="end" priority={3}>
          {/* A view switcher, not a single action: the toolbar pattern gives
              those a high priority so they never collapse into the menu
              (higher priority survives longer — a lower number overflows
              first). Icon-only, because the page's tab bar sits right above
              it: two text strips stacked read as two levels of navigation,
              while this one is a tool inside the Leads tab. */}
          <ViewToggle value={viewMode} onChange={setViewMode} options={VIEW_OPTIONS} />
        </nldd-toolbar-item>
        <nldd-toolbar-item slot="end" priority={2}>
          <NlddButton startIcon="plus" onClick={() => setShowIntake(true)} text="Nieuwe lead" />
          <nldd-menu-item slot="overflow" text="Nieuwe lead" icon="plus"></nldd-menu-item>
        </nldd-toolbar-item>
      </nldd-toolbar>

      {viewMode === 'inbox' ? (
        <LeadInboxView searchQuery={searchQuery} initiatiefId={initiatiefId} />
      ) : viewMode === 'kanban' ? (
        <LeadKanbanBoard
          searchQuery={searchQuery}
          initiatiefId={initiatiefId}
          assigneeId={filterAssignee}
          tag={filterTag}
          nextActionFilter={nextActionFilter}
          stageFilter={filterStage}
        />
      ) : viewMode === 'list' ? (
        <LeadListView
          searchQuery={searchQuery}
          initiatiefId={initiatiefId}
          assigneeId={filterAssignee}
          tag={filterTag}
          nextActionFilter={nextActionFilter}
          stageFilter={filterStage}
        />
      ) : viewMode === 'timeline' ? (
        <LeadTimelineView
          searchQuery={searchQuery}
          initiatiefId={initiatiefId}
          assigneeId={filterAssignee}
          stageFilter={filterStage}
        />
      ) : (
        <LeadGraphView searchQuery={searchQuery} initiatiefId={initiatiefId} stageFilter={filterStage} />
      )}

      <LeadIntakeDialog
        open={showIntake}
        onClose={() => { setShowIntake(false); setDroppedFiles([]); }}
        defaultInitiatiefId={initiatiefId}
        initialFiles={droppedFiles.length > 0 ? droppedFiles : undefined}
      />
    </nldd-container>
  );
}
