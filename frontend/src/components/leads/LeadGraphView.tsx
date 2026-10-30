import { useState, useMemo, useCallback, useEffect, useRef, memo } from 'react';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import { useIsMobile } from '@/hooks/useMediaQuery';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  MarkerType,
  useNodesState,
  useEdgesState,
  ReactFlowProvider,
  Handle,
  Position,
  type Node as RFNode,
  type Edge as RFEdge,
  type NodeProps,
  type Connection,
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';

import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { EmptyState } from '@/components/common/EmptyState';
import { LeadMetricsBar } from './LeadMetricsBar';
import { CommunityEdgeModal } from './CommunityEdgeModal';
import { AddLeadContactModal } from './AddLeadContactModal';
import { useCommunityGraph } from '@/hooks/useLeads';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import {
  LEAD_STAGE_LABELS,
  LeadStage,
  NodeType,
  entityColorVar,
  nodeTypeColor,
  formatFunctie,
  SAMENWERKINGSVERBAND_TYPE_LABELS,
} from '@/types';
import type { CommunityGraphNode, CommunityGraphEdge } from '@/types';
import { stageTagColor } from './stageColors';
import { resolveColor } from '@/utils/resolveColor';
import {
  EDGE_COLOR,
  EDGE_LABEL_BG_COLOR,
  EDGE_LABEL_COLOR,
  FLOATING_PANEL_STYLE,
  GRID_COLOR,
  MINIMAP_MASK_COLOR,
} from '@/components/graph/graphColors';

/** `stageTagColor` gives an nldd-tag color name, which is also a valid
 * Rijkshuisstijl/semantic token segment (`--primitives-color-<name>-500` or
 * `--semantics-content-<name>-color` for the semantic roles). The node's frame,
 * top bar and handles paint with it, so it has to resolve to a CSS value. */
function stageTagColorVar(stage: string): string {
  const name = stageTagColor(stage);
  if (name === 'success' || name === 'warning' || name === 'critical' || name === 'accent') {
    return `var(--semantics-content-${name}-color)`;
  }
  return `var(--primitives-color-${name}-500)`;
}

const PERSON_INTERN_COLOR = entityColorVar('roze');
const PERSON_EXTERN_COLOR = entityColorVar('oranje');
// Teal, which no entity color is; mintgroen is the nearest Rijkshuisstijl hue.
const ORG_COLOR = 'var(--primitives-color-mintgroen-500)';
const SWV_COLOR = entityColorVar('paars');
const CORPUS_NODE_FALLBACK = entityColorVar('coolgray');

// ---- Community node type to rank (swim-lane y) ----
// Strikte horizontale swim-lanes per node-type, top-down. Y wordt opgelegd
// via LANE_Y; dagre regelt alleen nog x-positie en cross-minimization.
// Externe orgs bovenaan, interne thuis-organisaties helemaal onderaan
// (onder de interne mensen die er werken).
const RANK_ORG_EXTERN = 0;
const RANK_CORPUS_NODE = 1;
const RANK_LEAD = 2;
const RANK_SAMENWERKINGSVERBAND = 3;
const RANK_PERSON_EXTERN = 4;
const RANK_PERSON_INTERN = 5;
const RANK_ORG_INTERN = 6;
const RANK_DEFAULT = RANK_LEAD;

const LANE_Y: Record<number, number> = {
  [RANK_ORG_EXTERN]: 40,
  [RANK_CORPUS_NODE]: 240,
  [RANK_LEAD]: 440,
  [RANK_SAMENWERKINGSVERBAND]: 640,
  [RANK_PERSON_EXTERN]: 840,
  [RANK_PERSON_INTERN]: 1040,
  [RANK_ORG_INTERN]: 1240,
};

function getNodeRank(node: CommunityGraphNode): number {
  if (node.node_type === 'person') {
    return node.person_role === 'extern' ? RANK_PERSON_EXTERN : RANK_PERSON_INTERN;
  }
  if (node.node_type === 'organisation') {
    return node.org_role === 'intern' ? RANK_ORG_INTERN : RANK_ORG_EXTERN;
  }
  if (node.node_type === 'samenwerkingsverband') return RANK_SAMENWERKINGSVERBAND;
  if (node.node_type === 'corpus_node') return RANK_CORPUS_NODE;
  if (node.node_type === 'lead') return RANK_LEAD;
  return RANK_DEFAULT;
}

// ---- Edge type styling ----
interface EdgeStyle {
  color: string;
  strokeDasharray?: string;
  strokeWidth: number;
  animated?: boolean;
  label: string;
}

function edgeStyle(edgeType: string): EdgeStyle {
  switch (edgeType) {
    case 'verantwoordelijke':
      return { color: entityColorVar('lintblauw'), strokeWidth: 1.5, label: 'verantwoordelijk' };
    case 'contact':
      return { color: entityColorVar('groen'), strokeDasharray: '5 5', strokeWidth: 1.5, label: 'contact' };
    case 'organisatie':
      return { color: ORG_COLOR, strokeWidth: 1.5, label: 'organisatie' };
    case 'gelinkt':
      return { color: entityColorVar('coolgray'), strokeWidth: 1.5, label: 'gelinkt' };
    case 'eigenaar':
    case 'betrokken':
    case 'adviseur':
      return { color: SWV_COLOR, strokeDasharray: '2 4', strokeWidth: 1.5, label: edgeType };
    case 'lid_van':
      return { color: EDGE_COLOR, strokeWidth: 1, label: 'lid van' };
    case 'lid_van_swv':
      return {
        color: SWV_COLOR,
        strokeDasharray: '4 3',
        strokeWidth: 1.25,
        label: edgeType === 'lid_van_swv' ? 'lid' : edgeType,
      };
    default:
      // Corpus node edges and anything else
      return { color: EDGE_COLOR, strokeWidth: 1.5, label: edgeType.replace(/_/g, ' ') };
  }
}

// ---- Custom node component ----
type CommunityNodeType =
  | 'lead'
  | 'person'
  | 'organisation'
  | 'corpus_node'
  | 'samenwerkingsverband';

interface CommunityGraphNodeData {
  label: string;
  nodeType: CommunityNodeType;
  stage?: string | null;
  functie?: string | null;
  expertise?: string | null;
  personRole?: 'intern' | 'extern' | null;
  orgType?: string | null;
  orgRole?: 'intern' | 'extern' | null;
  swvType?: string | null;
  corpusNodeType?: string | null;
  dimmed?: boolean;
  onClick?: () => void;
  onAddContact?: () => void;
}

function getNodeColor(data: CommunityGraphNodeData): string {
  if (data.nodeType === 'lead') {
    return stageTagColorVar(data.stage ?? '');
  }
  if (data.nodeType === 'person') {
    return data.personRole === 'extern' ? PERSON_EXTERN_COLOR : PERSON_INTERN_COLOR;
  }
  if (data.nodeType === 'organisation') return ORG_COLOR;
  if (data.nodeType === 'samenwerkingsverband') return SWV_COLOR;
  if (data.nodeType === 'corpus_node' && data.corpusNodeType) {
    return nodeTypeColor(data.corpusNodeType as NodeType);
  }
  return CORPUS_NODE_FALLBACK;
}

function CommunityGraphNodeComponent({ data }: NodeProps<CommunityGraphNodeData>) {
  const color = getNodeColor(data);
  const borderColor =
    data.nodeType === 'organisation' && data.orgRole === 'intern'
      ? PERSON_INTERN_COLOR
      : color;

  const badgeContent = (() => {
    if (data.nodeType === 'lead' && data.stage) {
      // De stage is sinds per-initiatief-kolommen een vrije slug. We pakken
      // alleen de vaste fallback-stijlen voor de 7 defaults; voor custom
      // kolommen valt de styling terug op een neutraal grijs en wordt de
      // slug zelf getoond — een per-graph-node lookup van de actieve
      // LeadColumn lijst zou hier overkill zijn.
      const fallbackKey = data.stage as LeadStage;
      return (
        <div className="hug">
          <nldd-tag
            text={LEAD_STAGE_LABELS[fallbackKey] ?? data.stage}
            color={stageTagColor(fallbackKey)}
            size="sm"
          />
        </div>
      );
    }
    if (data.nodeType === 'person') {
      const isExtern = data.personRole === 'extern';
      const roleLabel = isExtern ? 'Extern' : 'Intern';
      const functieLabel = formatFunctie(data.functie);
      const label = functieLabel ? `${roleLabel} · ${functieLabel}` : roleLabel;
      return (
        <nldd-container gap="2">
          <NodeKindLabel icon={isExtern ? 'person-circle' : 'person'} color={color} text={label} />
          {data.expertise && (
            <nldd-text size="xs" color="secondary">
              {data.expertise}
            </nldd-text>
          )}
        </nldd-container>
      );
    }
    if (data.nodeType === 'organisation') {
      const isIntern = data.orgRole === 'intern';
      const badgeColor = isIntern ? PERSON_INTERN_COLOR : color;
      const orgTypeLabel = data.orgType ?? 'Organisatie';
      const label = isIntern
        ? data.orgType
          ? `Intern · ${data.orgType}`
          : 'Intern'
        : orgTypeLabel;
      return <NodeKindLabel icon="apartment-building" color={badgeColor} text={label} truncate />;
    }
    if (data.nodeType === 'corpus_node') {
      return (
        <NodeKindLabel
          icon="file-text"
          color={color}
          text={data.corpusNodeType?.replace(/_/g, ' ') ?? 'Node'}
        />
      );
    }
    if (data.nodeType === 'samenwerkingsverband') {
      const typeLabel = data.swvType
        ? SAMENWERKINGSVERBAND_TYPE_LABELS[data.swvType] ?? data.swvType
        : 'Verband';
      return <NodeKindLabel icon="handshake" color={color} text={typeLabel} />;
    }
    return null;
  })();

  return (
    <div
      onClick={data.onClick}
      style={{
        background: 'var(--semantics-surfaces-base-background-color)',
        borderRadius: 'var(--semantics-surfaces-corner-radius)',
        // The node color at a third: a var() takes no hex alpha suffix, so mix instead.
        border: `1px solid color-mix(in oklch, ${borderColor} 33%, transparent)`,
        minWidth: '160px',
        maxWidth: '220px',
        cursor: data.onClick ? 'pointer' : 'default',
        overflow: 'hidden',
        opacity: data.dimmed ? 0.18 : 1,
        transition: 'opacity 150ms ease',
        pointerEvents: data.dimmed ? 'none' : 'auto',
      }}
    >
      {/* Colored top bar; the frame's overflow clips it to the corners. */}
      <div style={{ height: '4px', background: color }} />
      <nldd-container gap="4" padding-block="8" padding-inline="12">
        {badgeContent}
        <nldd-container layout="row" gap="4" vertical-alignment="bottom">
          <nldd-text size="sm" weight="medium" className="line-clamp-2 row-fill">
            {data.label}
          </nldd-text>
          {data.onAddContact && <AddContactButton onAdd={data.onAddContact} />}
        </nldd-container>
      </nldd-container>
      <Handle
        type="target"
        position={Position.Top}
        style={{ width: '8px', height: '8px', background: color, border: '2px solid var(--semantics-surfaces-base-background-color)', top: '-4px' }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ width: '8px', height: '8px', background: color, border: '2px solid var(--semantics-surfaces-base-background-color)', bottom: '-4px' }}
      />
    </div>
  );
}

/**
 * What kind of thing a node is: an icon in the node's own color, which ties
 * the node to the legend in the type toggles above the canvas, and the kind
 * in words beside it.
 */
function NodeKindLabel({
  icon,
  color,
  text,
  truncate = false,
}: {
  icon: string;
  color: string;
  text: string;
  truncate?: boolean;
}) {
  return (
    <nldd-container layout="row" gap="4" vertical-alignment="center">
      <nldd-icon icon={icon} size="16" custom-color={color} aria-hidden="true" />
      <nldd-text
        size="xs"
        weight="medium"
        color="secondary"
        className={truncate ? 'truncate row-fill' : 'row-fill'}
      >
        {text}
      </nldd-text>
    </nldd-container>
  );
}

/**
 * The + on a lead node. `nodrag` tells reactflow not to start a node drag from
 * it, and stopPropagation keeps the click from also opening the lead: the
 * element's own listener runs before React's root listener sees the click.
 */
function AddContactButton({ onAdd }: { onAdd: () => void }) {
  return (
    <NlddIconButton
      icon="plus"
      accessibleLabel="Contact toevoegen"
      variant="neutral-tinted"
      size="xs"
      className="nodrag"
      onClick={(event) => {
        event.stopPropagation();
        onAdd();
      }}
    />
  );
}

const CommunityGraphNodeMemo = memo(CommunityGraphNodeComponent);
const nodeTypes = { communityNode: CommunityGraphNodeMemo };

// ---- Dagre layout ----
function computeLayout(
  nodes: CommunityGraphNode[],
  edges: CommunityGraphEdge[],
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  if (nodes.length === 0) return positions;
  const nodeRankMap = new Map(nodes.map((n) => [n.id, getNodeRank(n)]));

  const nodeIds = new Set(nodes.map((n) => n.id));

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  // We overschrijven dagre's y-output met LANE_Y, dus ranksep en edgesep
  // hebben geen visuele werking meer. nodesep en align bepalen nog wel
  // x-positie binnen een lane.
  g.setGraph({
    rankdir: 'TB',
    nodesep: 70,
    marginx: 40,
    marginy: 40,
    align: 'UL',
  });

  for (const node of nodes) {
    g.setNode(node.id, { width: 200, height: 80 });
  }

  for (const edge of edges) {
    if (nodeIds.has(edge.source) && nodeIds.has(edge.target)) {
      g.setEdge(edge.source, edge.target);
    }
  }

  dagre.layout(g);

  for (const node of nodes) {
    const n = g.node(node.id);
    if (n) {
      const rank = nodeRankMap.get(node.id) ?? RANK_DEFAULT;
      positions.set(node.id, { x: n.x - 100, y: LANE_Y[rank] ?? LANE_Y[RANK_DEFAULT] });
    }
  }

  return positions;
}

// ---- Filter bar types ----
interface NodeTypeToggle {
  key: CommunityNodeType;
  label: string;
  icon: string;
  /** The color the canvas paints this kind of node in, so the toggle's icon
   *  doubles as the legend. Leads follow their stage and beleidsnodes their
   *  own type, so those two have no single color and stay uncolored. */
  color?: string;
}

const NODE_TYPE_TOGGLES: NodeTypeToggle[] = [
  { key: 'lead', label: 'Leads', icon: 'lightbulb' },
  { key: 'person', label: 'Personen', icon: 'person', color: PERSON_INTERN_COLOR },
  { key: 'organisation', label: 'Organisaties', icon: 'apartment-building', color: ORG_COLOR },
  { key: 'samenwerkingsverband', label: 'Verbanden', icon: 'handshake', color: SWV_COLOR },
  { key: 'corpus_node', label: 'Beleidsnodes', icon: 'file-text' },
];

/**
 * The node-type filter as a checkbox toggle group. nldd-toggle-button has no
 * color of its own, so the type color rides on the slotted icon; the selected
 * state is the button's own.
 */
function NodeTypeToggles({
  enabledTypes,
  onToggle,
}: {
  enabledTypes: Set<CommunityNodeType>;
  onToggle: (type: CommunityNodeType) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(
    ref,
    'change',
    useCallback(
      (event: Event) => {
        const value = (event as CustomEvent<{ value?: string }>).detail?.value;
        if (value) onToggle(value as CommunityNodeType);
      },
      [onToggle],
    ),
  );

  return (
    <nldd-toggle-button-group ref={ref} type="checkbox" size="sm" accessible-label="Toon in netwerk">
      {NODE_TYPE_TOGGLES.map((toggle) => (
        <nldd-toggle-button
          key={toggle.key}
          value={toggle.key}
          text={toggle.label}
          variant="icon-and-text"
          selected={orUndef(enabledTypes.has(toggle.key))}
        >
          <nldd-icon
            slot="icon"
            icon={toggle.icon}
            {...(toggle.color ? { 'custom-color': toggle.color } : {})}
          />
        </nldd-toggle-button>
      ))}
    </nldd-toggle-button-group>
  );
}

// ---- Inner component ----
interface CommunityGraphInnerProps {
  searchQuery?: string;
  initiatiefId: string;
  stageFilter?: string;
}

function CommunityGraphInner({
  searchQuery: searchQueryProp = '',
  initiatiefId,
  stageFilter: stageFilterProp = '',
}: CommunityGraphInnerProps) {
  const isMobile = useIsMobile();
  const { data, isLoading, error } = useCommunityGraph(initiatiefId || undefined);
  const { openLeadDetail } = useLeadDetail();
  const { openNodeDetail } = useNodeDetail();

  // Stable refs so layout memo doesn't recompute on every render
  const openLeadDetailRef = useRef(openLeadDetail);
  openLeadDetailRef.current = openLeadDetail;
  const openNodeDetailRef = useRef(openNodeDetail);
  openNodeDetailRef.current = openNodeDetail;

  // Edge creation state (drag-to-connect)
  const [pendingConnection, setPendingConnection] = useState<Connection | null>(null);
  const handleConnect = useCallback((connection: Connection) => {
    if (connection.source && connection.target) {
      setPendingConnection(connection);
    }
  }, []);

  // Add contact state (+ button on lead nodes)
  const [addContactLeadId, setAddContactLeadId] = useState<string | null>(null);
  const addContactRef = useRef((leadId: string) => setAddContactLeadId(leadId));
  addContactRef.current = (leadId: string) => setAddContactLeadId(leadId);

  // Focus mode: dim everything outside a 2-hop neighbourhood around one node.
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const setFocusRef = useRef((id: string | null) => setFocusedNodeId(id));
  setFocusRef.current = (id: string | null) => setFocusedNodeId(id);

  // View-specific filter: node type toggles
  const [enabledTypes, setEnabledTypes] = useState<Set<CommunityNodeType>>(
    new Set(['lead', 'person', 'organisation', 'samenwerkingsverband', 'corpus_node']),
  );

  const toggleType = useCallback((type: CommunityNodeType) => {
    setEnabledTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }, []);

  // Build all RF nodes and edges from data (stable layout)
  const { allRfNodes, allRfEdges } = useMemo(() => {
    if (!data?.nodes?.length) return { allRfNodes: [], allRfEdges: [] };

    const positions = computeLayout(data.nodes, data.edges);

    const allRfNodes: RFNode<CommunityGraphNodeData>[] = data.nodes.map((node) => {
      const pos = positions.get(node.id) ?? { x: 0, y: 0 };
      // Determine click handler based on node type
      const rawId = node.id.replace(/^(lead|person|org|node)-/, '');
      let onClick: (() => void) | undefined;
      let onAddContact: (() => void) | undefined;
      if (node.node_type === 'lead') {
        onClick = () => openLeadDetailRef.current(rawId);
        onAddContact = () => addContactRef.current(rawId);
      } else if (node.node_type === 'corpus_node') {
        onClick = () => openNodeDetailRef.current(rawId);
      } else if (node.node_type === 'person' || node.node_type === 'organisation') {
        // Click on a person/organisation focuses the graph on that node's neighbourhood
        // instead of opening a detail panel (there is no detail panel for these).
        onClick = () => setFocusRef.current(node.id);
      }

      return {
        id: node.id,
        type: 'communityNode',
        position: pos,
        data: {
          label: node.label,
          nodeType: node.node_type,
          stage: node.stage,
          functie: node.functie,
          expertise: node.expertise,
          personRole: node.person_role ?? null,
          orgType: node.org_type,
          orgRole: node.org_role ?? null,
          swvType: node.samenwerkingsverband_type ?? null,
          corpusNodeType: node.corpus_node_type,
          onClick,
          onAddContact,
        },
      };
    });

    const allRfEdges: RFEdge[] = data.edges.map((edge) => {
      const style = edgeStyle(edge.edge_type);
      const fromPos = positions.get(edge.source);
      const toPos = positions.get(edge.target);
      const goesUpward = fromPos && toPos && fromPos.y > toPos.y;
      const marker = { type: MarkerType.ArrowClosed, width: 16, height: 16, color: style.color };

      return {
        id: edge.id,
        source: goesUpward ? edge.target : edge.source,
        target: goesUpward ? edge.source : edge.target,
        label: edge.label ?? style.label,
        type: 'bezier',
        animated: style.animated ?? false,
        ...(goesUpward ? { markerStart: marker } : { markerEnd: marker }),
        style: {
          stroke: style.color,
          strokeWidth: style.strokeWidth,
          strokeDasharray: style.strokeDasharray,
        },
        labelStyle: { fontSize: 10, fill: EDGE_LABEL_COLOR, fontWeight: 500 },
        labelBgStyle: { fill: EDGE_LABEL_BG_COLOR, fillOpacity: 0.9 },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 4,
      };
    });

    return { allRfNodes, allRfEdges };
  }, [data]);

  // A search query that matches a person's name auto-focuses on that person.
  // For non-person matches the query falls back to the existing hide-by-name behaviour.
  const searchFocusId = useMemo(() => {
    const q = searchQueryProp.trim().toLowerCase();
    if (!q) return null;
    const matchingPerson = allRfNodes.find((n) => {
      const d = n.data as CommunityGraphNodeData;
      return d.nodeType === 'person' && d.label.toLowerCase().includes(q);
    });
    return matchingPerson?.id ?? null;
  }, [allRfNodes, searchQueryProp]);

  // Active focus is either an explicit click-set focus or, if none, a search-driven focus.
  const activeFocusId = focusedNodeId ?? searchFocusId;

  // BFS over the (undirected) edge graph up to depth=2 from the focused node.
  const focusedSet = useMemo(() => {
    if (!activeFocusId) return null;
    const adjacency = new Map<string, Set<string>>();
    for (const edge of allRfEdges) {
      if (!adjacency.has(edge.source)) adjacency.set(edge.source, new Set());
      if (!adjacency.has(edge.target)) adjacency.set(edge.target, new Set());
      adjacency.get(edge.source)!.add(edge.target);
      adjacency.get(edge.target)!.add(edge.source);
    }
    const visited = new Set<string>([activeFocusId]);
    let frontier: string[] = [activeFocusId];
    for (let depth = 0; depth < 2; depth += 1) {
      const next: string[] = [];
      for (const id of frontier) {
        for (const nb of adjacency.get(id) ?? []) {
          if (!visited.has(nb)) {
            visited.add(nb);
            next.push(nb);
          }
        }
      }
      frontier = next;
      if (frontier.length === 0) break;
    }
    return visited;
  }, [activeFocusId, allRfEdges]);

  // Apply filters (type toggles, stage, initiative) and focus dimming.
  // Search-as-hide only kicks in when the query does not match a person — otherwise
  // the matching person becomes the focus target and everything stays visible-but-dimmed.
  const { rfNodes, rfEdges } = useMemo(() => {
    const q = searchQueryProp.trim().toLowerCase();
    const searchActsAsFocus = searchFocusId !== null;
    const visibleIds = new Set<string>();

    const rfNodes = allRfNodes.map((node) => {
      const d = node.data as CommunityGraphNodeData;
      const matchesType = enabledTypes.has(d.nodeType);
      const matchesStage = !stageFilterProp || d.nodeType !== 'lead' || d.stage === stageFilterProp;
      const matchesSearch = !q || searchActsAsFocus || d.label.toLowerCase().includes(q);
      const isVisible = matchesType && matchesStage && matchesSearch;
      if (isVisible) visibleIds.add(node.id);
      const dimmed = isVisible && focusedSet !== null && !focusedSet.has(node.id);
      return { ...node, hidden: !isVisible, data: { ...d, dimmed } };
    });

    const rfEdges = allRfEdges.map((edge) => {
      const bothVisible = visibleIds.has(edge.source) && visibleIds.has(edge.target);
      const dimmed =
        bothVisible &&
        focusedSet !== null &&
        !(focusedSet.has(edge.source) && focusedSet.has(edge.target));
      const baseStyle = edge.style ?? {};
      return {
        ...edge,
        hidden: !bothVisible,
        style: dimmed ? { ...baseStyle, opacity: 0.12 } : { ...baseStyle, opacity: 1 },
        labelStyle: dimmed
          ? { ...edge.labelStyle, opacity: 0.2 }
          : edge.labelStyle,
      };
    });

    return { rfNodes, rfEdges };
  }, [
    allRfNodes,
    allRfEdges,
    enabledTypes,
    stageFilterProp,
    searchQueryProp,
    searchFocusId,
    focusedSet,
  ]);

  // React Flow state
  const [nodes, setNodes, onNodesChange] = useNodesState(rfNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(rfEdges);

  useEffect(() => {
    setNodes(rfNodes);
    setEdges(rfEdges);
  }, [rfNodes, rfEdges, setNodes, setEdges]);

  // Minimap coloring
  const minimapNodeColor = useCallback((node: RFNode) => {
    const d = node.data as CommunityGraphNodeData;
    // The minimap paints this as an SVG attribute, which cannot read a var().
    return resolveColor(getNodeColor(d));
  }, []);

  if (isLoading) {
    return <LoadingSpinner padding="32" />;
  }

  if (error) {
    return (
      <EmptyState
        title="Fout bij laden"
        description="Er is een fout opgetreden bij het laden van het netwerk. Probeer het opnieuw."
      />
    );
  }

  if (!data?.nodes?.length) {
    return (
      <EmptyState
        title="Geen data gevonden"
        description="Er zijn nog geen leads of gerelateerde gegevens om weer te geven in het netwerk."
      />
    );
  }

  return (
    <nldd-container gap="16">
      <LeadMetricsBar initiatiefId={initiatiefId || undefined} />

      {/* Node type toggles + focus indicator */}
      <nldd-container layout="row" gap="8" vertical-alignment="center">
        <nldd-container width="fit-content" className="row-fill">
          <NodeTypeToggles enabledTypes={enabledTypes} onToggle={toggleType} />
        </nldd-container>
        {focusedNodeId && (
          <NlddButton
            variant="neutral-tinted"
            size="sm"
            startIcon="close"
            text="Focus opheffen"
            title="Toon weer alle nodes"
            onClick={() => setFocusedNodeId(null)}
          />
        )}
      </nldd-container>

      {/* Graph canvas */}
      <div
        className="graph-canvas-frame"
        style={{ height: 'calc(100vh - 320px)', minHeight: isMobile ? '300px' : '500px' }}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={handleConnect}
          onPaneClick={() => setFocusedNodeId(null)}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2, maxZoom: 1.5 }}
          minZoom={0.1}
          maxZoom={3}
          defaultEdgeOptions={{ type: 'bezier' }}
          proOptions={{ hideAttribution: true }}
        >
          <Background color={resolveColor(GRID_COLOR)} gap={20} size={1} />
          <Controls showInteractive={false} style={FLOATING_PANEL_STYLE} />
          {!isMobile && (
            <MiniMap
              nodeColor={minimapNodeColor}
              maskColor={resolveColor(MINIMAP_MASK_COLOR)}
              style={FLOATING_PANEL_STYLE}
            />
          )}
        </ReactFlow>
      </div>

      <CommunityEdgeModal
        pendingConnection={pendingConnection}
        onClose={() => setPendingConnection(null)}
      />

      <AddLeadContactModal
        leadId={addContactLeadId}
        onClose={() => setAddContactLeadId(null)}
      />
    </nldd-container>
  );
}

// Wrap in ReactFlowProvider
interface LeadGraphViewProps {
  searchQuery?: string;
  initiatiefId: string;
  stageFilter?: string;
}

export function LeadGraphView({ searchQuery, initiatiefId, stageFilter }: LeadGraphViewProps) {
  return (
    <ReactFlowProvider>
      <CommunityGraphInner
        searchQuery={searchQuery}
        initiatiefId={initiatiefId}
        stageFilter={stageFilter}
      />
    </ReactFlowProvider>
  );
}
