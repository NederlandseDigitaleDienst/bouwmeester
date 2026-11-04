import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ViewToggle } from '@/components/common/ViewToggle';
import type { ViewToggleOption } from '@/components/common/ViewToggle';
import { MultiSelect } from '@/components/common/MultiSelect';
import type { MultiSelectOption } from '@/components/common/MultiSelect';
import { Select } from '@/components/common/Select';
import { NodeList } from '@/components/nodes/NodeList';
import { NodeCreateForm } from '@/components/nodes/NodeCreateForm';
import { ExportButton } from '@/components/nodes/ExportButton';
import { CorpusGraph } from '@/components/graph/CorpusGraph';
import { CorpusMatrix } from '@/components/graph/CorpusMatrix';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { NodeType } from '@/types';
import { useVocabulary } from '@/contexts/VocabularyContext';
import { useGraphView } from '@/hooks/useGraph';
import { useDebounce } from '@/hooks/useDebounce';
import { useGlobalFileDropContext } from '@/hooks/useGlobalFileDropContext';
import { NlddButton } from '@/components/nldd/NlddButton';

type ViewMode = 'list' | 'graph' | 'matrix';

const VIEW_OPTIONS: ViewToggleOption<ViewMode>[] = [
  { value: 'list', label: 'Lijst', icon: 'square-grid-2x2' },
  { value: 'graph', label: 'Netwerk', icon: 'git-fork' },
  { value: 'matrix', label: 'Matrix', icon: 'square-grid-3x3' },
];

const ALL_NODE_TYPES = Object.values(NodeType);

/** The corpus search field: `nldd-search-field` with its `input` event bridged to React. */
function CorpusSearchField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));
  return (
    <nldd-search-field
      ref={ref}
      value={value}
      placeholder="Zoek in corpus..."
      accessible-label="Zoek in corpus"
    />
  );
}

export function CorpusPage() {
  const [showCreateForm, setShowCreateForm] = useState(false);
  const { subscribe } = useGlobalFileDropContext();
  const [droppedFile, setDroppedFile] = useState<File | undefined>(undefined);

  // Subscribe to global file drops while this page is mounted
  useEffect(() => {
    return subscribe((files) => {
      setDroppedFile(files[0]);
      setShowCreateForm(true);
    });
  }, [subscribe]);
  const [searchParams, setSearchParams] = useSearchParams();
  const viewParam = searchParams.get('view');
  const viewMode: ViewMode = viewParam === 'graph' ? 'graph' : viewParam === 'matrix' ? 'matrix' : 'list';
  const { nodeLabel, edgeLabel: vocabEdgeLabel } = useVocabulary();

  // Node type filter: derived from URL, omit param when all selected
  const enabledNodeTypes = useMemo<Set<NodeType>>(() => {
    const typesParam = searchParams.get('types');
    if (!typesParam) return new Set(ALL_NODE_TYPES);
    if (typesParam === 'none') return new Set<NodeType>();
    const parsed = typesParam
      .split(',')
      .filter((t) => ALL_NODE_TYPES.includes(t as NodeType)) as NodeType[];
    return parsed.length > 0 ? new Set(parsed) : new Set(ALL_NODE_TYPES);
  }, [searchParams]);

  // Search: local state for responsive typing, synced to URL via debounce
  const [searchInput, setSearchInput] = useState(() => searchParams.get('q') ?? '');
  const searchQuery = useDebounce(searchInput, 200);

  // Sync URL → local input when URL changes externally (e.g., browser back/forward)
  useEffect(() => {
    const urlQuery = searchParams.get('q') ?? '';
    setSearchInput((prev) => (prev !== urlQuery ? urlQuery : prev));
  }, [searchParams]);

  // Sync debounced search value to URL
  useEffect(() => {
    setSearchParams((prev) => {
      if (searchQuery) prev.set('q', searchQuery); else prev.delete('q');
      return prev;
    }, { replace: true });
  }, [searchQuery, setSearchParams]);

  // Edge type filter state (fetched in graph and matrix modes)
  const { data: graphData, isLoading: isGraphLoading, error: graphError } = useGraphView(undefined, undefined, viewMode === 'graph' || viewMode === 'matrix');

  const availableEdgeTypes = useMemo(() => {
    if (!graphData?.edges) return [];
    const types = new Set<string>();
    for (const edge of graphData.edges) {
      if (edge.edge_type_id) types.add(edge.edge_type_id);
    }
    return [...types].sort();
  }, [graphData?.edges]);

  // Edge type filter: derived from URL, default to all available when param absent
  const enabledEdgeTypes = useMemo<Set<string>>(() => {
    const edgesParam = searchParams.get('edges');
    if (!edgesParam) return new Set(availableEdgeTypes);
    if (edgesParam === 'none') return new Set<string>();
    const parsed = edgesParam.split(',').filter((t) => availableEdgeTypes.includes(t));
    return parsed.length > 0 ? new Set(parsed) : new Set(availableEdgeTypes);
  }, [searchParams, availableEdgeTypes]);

  const edgeTypeFilterOptions: MultiSelectOption[] = useMemo(
    () => availableEdgeTypes.map((t) => ({ value: t, label: vocabEdgeLabel(t) })),
    [availableEdgeTypes, vocabEdgeLabel],
  );

  const nodeTypeFilterOptions: MultiSelectOption[] = useMemo(() =>
    ALL_NODE_TYPES.map((t) => ({
      value: t,
      label: nodeLabel(t),
    })),
  [nodeLabel]);

  const handleNodeTypesChange = useCallback((next: Set<string>) => {
    setSearchParams((prev) => {
      const allSelected = ALL_NODE_TYPES.every((t) => next.has(t));
      if (allSelected) prev.delete('types');
      else if (next.size === 0) prev.set('types', 'none');
      else prev.set('types', [...next].join(','));
      return prev;
    }, { replace: true });
  }, [setSearchParams]);

  const handleEdgeTypesChange = useCallback((next: Set<string>) => {
    setSearchParams((prev) => {
      const allSelected = availableEdgeTypes.every((t) => next.has(t));
      if (allSelected) prev.delete('edges');
      else if (next.size === 0) prev.set('edges', 'none');
      else prev.set('edges', [...next].join(','));
      return prev;
    }, { replace: true });
  }, [setSearchParams, availableEdgeTypes]);

  // Matrix-specific: row and column node type selectors from URL
  const matrixRowType = (searchParams.get('rowType') as NodeType) || NodeType.DOEL;
  const matrixColType = (searchParams.get('colType') as NodeType) || NodeType.INSTRUMENT;

  const setMatrixRowType = useCallback((type: NodeType) => {
    setSearchParams((prev) => {
      prev.set('rowType', type);
      return prev;
    }, { replace: true });
  }, [setSearchParams]);

  const setMatrixColType = useCallback((type: NodeType) => {
    setSearchParams((prev) => {
      prev.set('colType', type);
      return prev;
    }, { replace: true });
  }, [setSearchParams]);

  const setViewMode = useCallback((mode: ViewMode) => {
    setSearchParams((prev) => {
      if (mode === 'list') {
        prev.delete('view');
      } else {
        prev.set('view', mode);
      }
      return prev;
    }, { replace: true });
  }, [setSearchParams]);

  return (
    <nldd-container gap="24">
      {/* Page header */}
      <nldd-toolbar accessible-label="Corpusacties">
        <nldd-toolbar-item slot="start" priority={1} min-width="60%">
          {/* Filters share the toolbar row with the actions, and wrap only
              when the room runs out. `min-width` makes the item fluid; a
              percentage lets it give way to the end items instead of pushing
              them into the overflow menu. Each field has a fixed width,
              because a fit-content container measures its children and they
              measure it back. */}
          <nldd-container layout="wrap" gap="8" vertical-alignment="center">
            <nldd-container width="224px">
              <CorpusSearchField value={searchInput} onChange={setSearchInput} />
            </nldd-container>
            {viewMode !== 'matrix' && (
              <nldd-container width="208px">
                <MultiSelect
                  value={enabledNodeTypes as Set<string>}
                  onChange={handleNodeTypesChange}
                  options={nodeTypeFilterOptions}
                  allLabel="Alle types"
                />
              </nldd-container>
            )}
            {(viewMode === 'graph' || viewMode === 'matrix') && edgeTypeFilterOptions.length > 0 && (
              <nldd-container width="208px">
                <MultiSelect
                  value={enabledEdgeTypes}
                  onChange={handleEdgeTypesChange}
                  options={edgeTypeFilterOptions}
                  allLabel="Alle relaties"
                />
              </nldd-container>
            )}
            {viewMode === 'matrix' && (
              <>
                <nldd-container width="176px">
                  <Select
                    value={matrixRowType}
                    onChange={(e) => setMatrixRowType(e.target.value as NodeType)}
                    options={ALL_NODE_TYPES.map((t) => ({ value: t, label: `${nodeLabel(t)} (rij)` }))}
                    aria-label="Rij-type"
                  />
                </nldd-container>
                <nldd-container width="176px">
                  <Select
                    value={matrixColType}
                    onChange={(e) => setMatrixColType(e.target.value as NodeType)}
                    options={ALL_NODE_TYPES.map((t) => ({ value: t, label: `${nodeLabel(t)} (kolom)` }))}
                    aria-label="Kolom-type"
                  />
                </nldd-container>
              </>
            )}
          </nldd-container>
        </nldd-toolbar-item>
        <nldd-toolbar-item slot="end" priority={3}>
          {/* A tab-like view switcher, not a single action: per the toolbar
              pattern this gets a high priority instead of an overflow
              alternative, so it never becomes a menu item. */}
          <ViewToggle value={viewMode} onChange={setViewMode} options={VIEW_OPTIONS} />
        </nldd-toolbar-item>
        <nldd-toolbar-item slot="end">
          {/* ExportButton owns its own anchored nldd-menu with four export
              formats; the overflow slot only takes flat menu items, so this
              is a single reasonable fallback action rather than the full
              submenu. */}
          <ExportButton hideLabel />
          <nldd-menu-item slot="overflow" text="Exporteren" icon="download"></nldd-menu-item>
        </nldd-toolbar-item>
        <nldd-toolbar-item slot="end" priority={2}>
          <NlddButton startIcon="plus" onClick={() => setShowCreateForm(true)} text="Nieuwe node" compactBelowSm />
          <nldd-menu-item slot="overflow" text="Nieuwe node" icon="plus"></nldd-menu-item>
        </nldd-toolbar-item>
      </nldd-toolbar>

      {/* View content */}
      {viewMode === 'list' ? (
        <NodeList enabledNodeTypes={enabledNodeTypes} searchQuery={searchQuery} />
      ) : viewMode === 'graph' ? (
        <CorpusGraph enabledNodeTypes={enabledNodeTypes} searchQuery={searchQuery} enabledEdgeTypes={enabledEdgeTypes} graphData={graphData} isLoading={isGraphLoading} error={graphError} />
      ) : viewMode === 'matrix' ? (
        <CorpusMatrix
          rowNodeType={matrixRowType}
          colNodeType={matrixColType}
          enabledEdgeTypes={enabledEdgeTypes}
          searchQuery={searchQuery}
          graphData={graphData}
          isLoading={isGraphLoading}
          error={graphError}
        />
      ) : null}

      {/* Create form modal */}
      <NodeCreateForm
        open={showCreateForm}
        onClose={() => { setShowCreateForm(false); setDroppedFile(undefined); }}
        initialBijlageFile={droppedFile}
      />
    </nldd-container>
  );
}
