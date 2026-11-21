import { useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Card } from '@/components/common/Card';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { EmptyState } from '@/components/common/EmptyState';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useVocabulary } from '@/contexts/VocabularyContext';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { entityColorVar, nodeTypeColor } from '@/types';
import type { NodeType, CorpusNode, GraphViewResponse } from '@/types';
import { useNlddEvent } from '@/components/nldd/events';
import { buildMatrixAdjacency, countUniqueEdges, type CellEdge } from '@/utils/matrixAdjacency';

const MAX_MATRIX_DIMENSION = 100;

/**
 * A node's title in a matrix header, as a link to that node.
 *
 * `nldd-link` with no `size` inherits the surrounding typography and stays
 * inline, so it sits in a header cell without reshaping it.
 *
 * `href` is the node's real route, so the browser's own gestures keep working:
 * cmd-click and middle-click open it in a tab, and the status bar shows where
 * it goes. A plain click is intercepted and opens the detail surface instead,
 * which keeps the matrix on screen behind it.
 *
 * The color rides on `--semantics-links-color`, not `color`: the link paints
 * itself from that token inside its shadow root, where a `color` set on the
 * host does not reach.
 */
function NodeTitleLink({
  nodeId,
  title,
  color,
  onOpen,
  className,
}: {
  nodeId: string;
  title: string;
  color: string;
  onOpen: () => void;
  className?: string;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', (event: Event) => {
    const mouse = event as MouseEvent;
    // A modified click asked for a new tab or window; let the browser do it.
    if (mouse.metaKey || mouse.ctrlKey || mouse.shiftKey || mouse.altKey || mouse.button === 1) {
      return;
    }
    event.preventDefault();
    onOpen();
  });
  return (
    <nldd-link
      ref={ref}
      href={`/nodes/${nodeId}`}
      text={title}
      title={title}
      className={className}
      style={{ '--semantics-links-color': color } as React.CSSProperties}
    />
  );
}

interface CorpusMatrixProps {
  rowNodeType: NodeType;
  colNodeType: NodeType;
  enabledEdgeTypes: Set<string>;
  searchQuery?: string;
  graphData?: GraphViewResponse;
  isLoading: boolean;
  error?: Error | null;
}

export function CorpusMatrix({
  rowNodeType,
  colNodeType,
  enabledEdgeTypes,
  searchQuery,
  graphData,
  isLoading,
  error,
}: CorpusMatrixProps) {
  const { edgeLabel } = useVocabulary();
  const { openNodeDetail } = useNodeDetail();
  const [searchParams, setSearchParams] = useSearchParams();
  const showFullMatrix = searchParams.get('fullMatrix') === '1';
  const [pendingExpand, setPendingExpand] = useState(false);

  const sameType = rowNodeType === colNodeType;

  // Filter nodes by type, then optionally by search
  const allRowNodes = useMemo(() => {
    if (!graphData?.nodes) return [];
    let nodes = graphData.nodes.filter((n: CorpusNode) => n.node_type === rowNodeType);
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      nodes = nodes.filter((n: CorpusNode) => n.title.toLowerCase().includes(q));
    }
    return nodes.sort((a: CorpusNode, b: CorpusNode) => a.title.localeCompare(b.title));
  }, [graphData?.nodes, rowNodeType, searchQuery]);

  const allColNodes = useMemo(() => {
    if (!graphData?.nodes) return [];
    if (sameType) return allRowNodes;
    let nodes = graphData.nodes.filter((n: CorpusNode) => n.node_type === colNodeType);
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      nodes = nodes.filter((n: CorpusNode) => n.title.toLowerCase().includes(q));
    }
    return nodes.sort((a: CorpusNode, b: CorpusNode) => a.title.localeCompare(b.title));
  }, [graphData?.nodes, colNodeType, searchQuery, sameType, allRowNodes]);

  // Apply dimension cap unless user opted to show full matrix
  const isTruncated = !showFullMatrix && (allRowNodes.length > MAX_MATRIX_DIMENSION || allColNodes.length > MAX_MATRIX_DIMENSION);
  const rowNodes = isTruncated ? allRowNodes.slice(0, MAX_MATRIX_DIMENSION) : allRowNodes;
  const colNodes = isTruncated ? allColNodes.slice(0, MAX_MATRIX_DIMENSION) : allColNodes;

  // Build adjacency using the extracted utility
  const adjacency = useMemo(() => {
    if (!graphData?.edges) return new Map<string, CellEdge[]>();
    const rowIds = new Set(rowNodes.map((n: CorpusNode) => n.id));
    const colIds = new Set(colNodes.map((n: CorpusNode) => n.id));
    return buildMatrixAdjacency(graphData.edges, rowIds, colIds, enabledEdgeTypes, sameType);
  }, [graphData?.edges, rowNodes, colNodes, enabledEdgeTypes, sameType]);

  const setShowFullMatrix = (show: boolean) => {
    setPendingExpand(false);
    setSearchParams((prev) => {
      if (show) prev.set('fullMatrix', '1'); else prev.delete('fullMatrix');
      return prev;
    }, { replace: true });
  };

  if (isLoading) {
    return <LoadingSpinner padding="48" />;
  }

  if (error) {
    return (
      <EmptyState
        title="Fout bij laden"
        description="Er is een fout opgetreden bij het laden van de data. Probeer het opnieuw."
      />
    );
  }

  if (allRowNodes.length === 0 && allColNodes.length === 0) {
    return <EmptyState title="Geen nodes gevonden voor de geselecteerde types." />;
  }

  if (allRowNodes.length === 0) {
    return <EmptyState title="Geen rij-nodes gevonden voor het geselecteerde type." />;
  }

  if (allColNodes.length === 0) {
    return <EmptyState title="Geen kolom-nodes gevonden voor het geselecteerde type." />;
  }

  const rowColor = nodeTypeColor(rowNodeType);
  const colColor = nodeTypeColor(colNodeType);
  const connectionCount = countUniqueEdges(adjacency);
  const totalCells = allRowNodes.length * allColNodes.length;

  return (
    <nldd-container gap="12">
      <nldd-text size="xs" color="secondary">
        <p>
          {rowNodes.length}{isTruncated && allRowNodes.length > MAX_MATRIX_DIMENSION ? ` van ${allRowNodes.length}` : ''} rijen
          {' '}&times;{' '}
          {colNodes.length}{isTruncated && allColNodes.length > MAX_MATRIX_DIMENSION ? ` van ${allColNodes.length}` : ''} kolommen
          {' '}&middot;{' '}
          {connectionCount} {connectionCount === 1 ? 'relatie' : 'relaties'}
          {sameType && ' (symmetrische matrix — zelfde type rij en kolom)'}
        </p>
      </nldd-text>

      {/* The actions are nldd-buttons, not inline action text: the banner
          wraps its `actions` slot in an nldd-button-group. */}
      {isTruncated && (
        pendingExpand ? (
          <nldd-banner
            variant="warning"
            size="sm"
            text={`Volledige matrix (${allRowNodes.length}×${allColNodes.length} = ${totalCells.toLocaleString('nl-NL')} cellen) kan de browser vertragen.`}
          >
            <NlddButton
              slot="actions"
              variant="secondary"
              size="sm"
              text="Toch tonen"
              onClick={() => setShowFullMatrix(true)}
            />
            <NlddButton
              slot="actions"
              variant="neutral-transparent"
              size="sm"
              text="Annuleren"
              onClick={() => setPendingExpand(false)}
            />
          </nldd-banner>
        ) : (
          <nldd-banner
            variant="warning"
            size="sm"
            text={`Matrix is beperkt tot ${MAX_MATRIX_DIMENSION}×${MAX_MATRIX_DIMENSION} voor prestatie.`}
            supporting-text="Gebruik de zoekbalk om te filteren, of toon alles."
          >
            <NlddButton
              slot="actions"
              variant="secondary"
              size="sm"
              text={`Toon alles (${allRowNodes.length}×${allColNodes.length})`}
              onClick={() => (totalCells > 10000 ? setPendingExpand(true) : setShowFullMatrix(true))}
            />
          </nldd-banner>
        )
      )}

      {showFullMatrix && !isTruncated && allRowNodes.length > MAX_MATRIX_DIMENSION && (
        <nldd-banner variant="accent" size="sm" text="Volledige matrix wordt getoond.">
          <NlddButton
            slot="actions"
            variant="secondary"
            size="sm"
            text={`Beperk tot ${MAX_MATRIX_DIMENSION}×${MAX_MATRIX_DIMENSION}`}
            onClick={() => setShowFullMatrix(false)}
          />
        </nldd-banner>
      )}

      <Card padding={false}>
        <div className="matrix-scroll-area">
          <table className="matrix-table" role="grid" aria-label="Relatiematrix">
            <thead className="matrix-thead">
              <tr role="row">
                <th className="matrix-corner-cell" role="columnheader" />
                {colNodes.map((col: CorpusNode, colIdx: number) => (
                  <th
                    key={col.id}
                    className="matrix-header-cell"
                    role="columnheader"
                    aria-colindex={colIdx + 2}
                  >
                    {/* The rotation lives on the wrapper, not the link: a
                        custom element cannot have its shadow content rotated
                        from outside, but it does inherit the writing mode. */}
                    <span
                      className="matrix-header-label"
                      style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
                    >
                      <NodeTitleLink
                        nodeId={col.id}
                        title={col.title}
                        color={colColor}
                        onOpen={() => openNodeDetail(col.id)}
                      />
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rowNodes.map((row: CorpusNode, rowIdx: number) => (
                <tr key={row.id} className="group" role="row" aria-rowindex={rowIdx + 2}>
                  {/* Row header — opaque bg prevents bleed-through on horizontal scroll */}
                  <td className="matrix-row-header group-hover-bg" role="rowheader">
                    <NodeTitleLink
                      nodeId={row.id}
                      title={row.title}
                      color={rowColor}
                      onOpen={() => openNodeDetail(row.id)}
                      className="matrix-row-header-link"
                    />
                  </td>
                  {colNodes.map((col: CorpusNode) => {
                    const key = `${row.id}_${col.id}`;
                    const cellEdges = adjacency.get(key);
                    const hasEdge = cellEdges && cellEdges.length > 0;
                    const isDiagonal = sameType && row.id === col.id;

                    // Build tooltip: edge types + both node titles
                    const tooltip = hasEdge
                      ? `${row.title} — ${cellEdges.map((e: CellEdge) => edgeLabel(e.edge_type_id)).join(', ')} — ${col.title}`
                      : undefined;

                    return (
                      <td
                        key={col.id}
                        className={`matrix-cell group-hover-bg ${isDiagonal ? 'matrix-cell-diagonal' : ''}`}
                        role="gridcell"
                        aria-label={hasEdge ? tooltip : undefined}
                      >
                        {isDiagonal ? (
                          <span className="matrix-dot-slot matrix-diagonal-mark">&mdash;</span>
                        ) : hasEdge ? (
                          <button
                            onClick={() => openNodeDetail(row.id)}
                            className="plain-button matrix-dot-button"
                            title={tooltip}
                            aria-label={tooltip}
                          >
                            <span
                              className="matrix-dot"
                              style={{
                                backgroundColor:
                                  cellEdges.length === 1
                                    ? nodeTypeColor(rowNodeType)
                                    : entityColorVar('violet'),
                                opacity: 0.8,
                              }}
                            />
                          </button>
                        ) : (
                          <span className="matrix-dot-slot" />
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </nldd-container>
  );
}
