import { useRef, useState, useMemo } from 'react';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import { NlddActionText } from '@/components/nldd/NlddLink';
import { useNodeGraph } from '@/hooks/useNodes';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { useCompletenessAnalysis, type StepStatus } from './useCompletenessAnalysis';
import { KCBR_MAIN_URL, KCBR_STAKEHOLDERS_URL } from './config';
import { GapAnalysisPanel } from './GapAnalysisPanel';
import { KompasStepSuggestions } from './KompasStepSuggestions';
import { LinkExistingNodeModal } from './LinkExistingNodeModal';
import { NodeCreateForm } from '../NodeCreateForm';
import { NODE_TYPE_LABELS, NODE_TYPE_LABELS_PLURAL, NODE_TYPE_COLORS, type NodeType } from '@/types';
import { EDGE_TYPE_ONDERDEEL_VAN } from './constants';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddListItemButton } from '@/components/nldd/NlddLink';

/**
 * A segment that discloses a row's children group: a chevron that flips, and a
 * click bridged to React. Sits beside a sibling segment (the KCBR link) so the
 * two actions stay independent rather than nesting a control inside a control.
 * `disclosure` marks this as the row's own disclosure control, which rotates
 * the slotted icon-cell a quarter turn while open — no manual class needed.
 */
function DisclosureSegment({
  expanded,
  onToggle,
  children,
}: {
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', onToggle);
  return (
    <nldd-list-item-segment ref={ref} button width="full" expanded={orUndef(expanded)} disclosure>
      {children}
      <nldd-icon-cell icon="chevron-down" size="16" />
    </nldd-list-item-segment>
  );
}

interface StepActionButtonsProps {
  nodeType: NodeType;
  onCreateNew: (nodeType: NodeType) => void;
  onLinkExisting: (nodeType: NodeType) => void;
}

function StepActionButtons({ nodeType, onCreateNew, onLinkExisting }: StepActionButtonsProps) {
  return (
    <nldd-container layout="row" gap="2" vertical-alignment="center">
      <NlddButton
        variant="neutral-transparent"
        size="sm"
        startIcon="plus"
        onClick={() => onCreateNew(nodeType)}
        text="Nieuw"
      />
      <NlddButton
        variant="neutral-transparent"
        size="sm"
        startIcon="link"
        onClick={() => onLinkExisting(nodeType)}
        text="Koppelen"
      />
    </nldd-container>
  );
}

interface BeleidskompasStepRowProps {
  status: StepStatus;
  dossierId: string;
  onCreateNew: (nodeType: NodeType) => void;
  onLinkExisting: (nodeType: NodeType) => void;
}

function StepNumberBadge({ number, complete }: { number: number; complete: boolean }) {
  return <nldd-badge number={number} color={complete ? 'success' : 'neutral'} size="md" />;
}

function stepCountLabel(status: StepStatus): string {
  if (status.step.nodeTypes.length === 1) {
    const nt = status.step.nodeTypes[0];
    if (status.count === 1) return `1 ${NODE_TYPE_LABELS[nt].toLowerCase()}`;
    return `${status.count} ${NODE_TYPE_LABELS_PLURAL[nt] ?? NODE_TYPE_LABELS[nt].toLowerCase()}`;
  }
  // Multi-type step: use pre-computed counts per type
  const parts: string[] = [];
  for (const nt of status.step.nodeTypes) {
    const count = status.countsByType.get(nt) ?? 0;
    if (count === 0) continue;
    const label = count === 1
      ? NODE_TYPE_LABELS[nt].toLowerCase()
      : (NODE_TYPE_LABELS_PLURAL[nt] ?? NODE_TYPE_LABELS[nt].toLowerCase());
    parts.push(`${count} ${label}`);
  }
  return parts.join(', ');
}

/** Renders nodes and action buttons grouped by node type for a step. */
function StepTypeGroups({
  status,
  onCreateNew,
  onLinkExisting,
}: {
  status: StepStatus;
  onCreateNew: (nodeType: NodeType) => void;
  onLinkExisting: (nodeType: NodeType) => void;
}) {
  const { openNodeDetail } = useNodeDetail();
  const isMultiType = status.step.nodeTypes.length > 1;

  if (!isMultiType) {
    // Single type: show nodes flat, then action buttons
    return (
      <>
        {status.nodes.map((node) => (
          <NlddListItemButton key={node.id} onClick={() => openNodeDetail(node.id)}>
            <nldd-text-cell width="fit-content">
              <Badge color={NODE_TYPE_COLORS[node.node_type as NodeType]} dot>
                {NODE_TYPE_LABELS[node.node_type as NodeType]}
              </Badge>
            </nldd-text-cell>
            <nldd-text-cell text={node.title} />
          </NlddListItemButton>
        ))}
        <StepActionButtons
          nodeType={status.step.nodeTypes[0]}
          onCreateNew={onCreateNew}
          onLinkExisting={onLinkExisting}
        />
      </>
    );
  }

  // Multi-type: group nodes and actions per type
  return (
    <nldd-container gap="8">
      {status.step.nodeTypes.map((nt) => {
        const typeNodes = status.nodes.filter(
          (n) => n.node_type === nt,
        );
        return (
          <nldd-container key={nt} gap="4" padding-left="8">
            <nldd-text size="xs" color="secondary" weight="medium">
              {NODE_TYPE_LABELS[nt]}:
            </nldd-text>
            <nldd-container gap="0">
              {typeNodes.map((node) => (
                <NlddListItemButton key={node.id} onClick={() => openNodeDetail(node.id)}>
                  <nldd-text-cell width="fit-content">
                    <Badge color={NODE_TYPE_COLORS[node.node_type as NodeType]} dot>
                      {NODE_TYPE_LABELS[node.node_type as NodeType]}
                    </Badge>
                  </nldd-text-cell>
                  <nldd-text-cell text={node.title} />
                </NlddListItemButton>
              ))}
            </nldd-container>
            <StepActionButtons
              nodeType={nt}
              onCreateNew={onCreateNew}
              onLinkExisting={onLinkExisting}
            />
          </nldd-container>
        );
      })}
    </nldd-container>
  );
}

function BeleidskompasStepRow({ status, dossierId, onCreateNew, onLinkExisting }: BeleidskompasStepRowProps) {
  const [expanded, setExpanded] = useState(false);

  if (status.isComplete) {
    return (
      <>
        <nldd-list-item>
          <DisclosureSegment expanded={expanded} onToggle={() => setExpanded((e) => !e)}>
            <nldd-icon-cell icon="check-mark-circle" color="success" />
            <StepNumberBadge number={status.step.number} complete />
            <nldd-title-cell text={status.step.question} />
            <nldd-text-cell width="fit-content" color="secondary" hide-below="sm" text={stepCountLabel(status)} />
          </DisclosureSegment>
          <nldd-list-item-segment href={status.step.kcbrUrl} target="_blank" width="fit-content" accessible-label="Bekijk op KCBR">
            <nldd-icon-cell icon="external-link" size="16" />
          </nldd-list-item-segment>
        </nldd-list-item>
        {expanded && (
          <nldd-list-item>
            <nldd-container padding-left="24" gap="6">
              <StepTypeGroups
                status={status}
                onCreateNew={onCreateNew}
                onLinkExisting={onLinkExisting}
              />
            </nldd-container>
          </nldd-list-item>
        )}
      </>
    );
  }

  // Incomplete step (may still have some nodes linked)
  return (
    <nldd-list-item>
      <nldd-container gap="8" width="full">
        <nldd-container layout="row" vertical-alignment="top" gap="12">
          <StepNumberBadge number={status.step.number} complete={false} />
          <nldd-icon icon="exclamation-triangle" size="20" color="warning" aria-hidden="true" />
          <nldd-container gap="0" width="full">
            <nldd-container layout="row" vertical-alignment="center" gap="6">
              <nldd-text size="sm" weight="medium">{status.step.question}</nldd-text>
              <nldd-link href={status.step.kcbrUrl} target="_blank" accessible-label="Bekijk op KCBR" start-icon="external-link" />
            </nldd-container>
            <nldd-text size="xs" color="secondary">{status.step.description}</nldd-text>
          </nldd-container>
        </nldd-container>
        <nldd-container padding-left="24" gap="6">
          <StepTypeGroups
            status={status}
            onCreateNew={onCreateNew}
            onLinkExisting={onLinkExisting}
          />
          <KompasStepSuggestions
            dossierId={dossierId}
            stepNodeTypes={status.step.nodeTypes}
            stepDescription={status.step.question}
          />
        </nldd-container>
      </nldd-container>
    </nldd-list-item>
  );
}

interface BeleidskompasPanelProps {
  nodeId: string;
  stakeholderCount: number;
  onNavigateToStakeholders: () => void;
}

export function BeleidskompasPanel({ nodeId, stakeholderCount, onNavigateToStakeholders }: BeleidskompasPanelProps) {
  const { data: graphData, isLoading, isError } = useNodeGraph(nodeId, 1);
  const { steps, completedCount, totalSteps } = useCompletenessAnalysis(graphData, nodeId);
  const [linkModalType, setLinkModalType] = useState<NodeType | null>(null);
  const [createModalType, setCreateModalType] = useState<NodeType | null>(null);

  // Collect IDs of nodes already linked to this dossier via onderdeel_van
  const linkedNodeIds = useMemo(() => {
    if (!graphData) return new Set<string>();
    const ids = new Set<string>();
    for (const edge of graphData.edges) {
      if (edge.edge_type_id === EDGE_TYPE_ONDERDEEL_VAN && edge.to_node_id === nodeId) {
        ids.add(edge.from_node_id);
      }
    }
    return ids;
  }, [graphData, nodeId]);

  if (isLoading) {
    return (
      <Card>
        <nldd-inline-dialog variant="loading" text="Beleidskompas laden..." />
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <nldd-inline-dialog
          icon="exclamation-triangle"
          text="Beleidskompas kon niet geladen worden."
        />
      </Card>
    );
  }

  return (
    <>
      <Card>
        <nldd-container gap="16">
          {/* Header */}
          <nldd-container layout="row" gap="8" vertical-alignment="center">
            <nldd-icon icon="signpost" size="20" color="accent" aria-hidden="true" />
            <nldd-title size={6}><h3>Beleidskompas</h3></nldd-title>
            <nldd-link href={KCBR_MAIN_URL} target="_blank" accessible-label="Bekijk Beleidskompas op KCBR" start-icon="external-link" />
            <nldd-spacer size="flexible" />
            {/* A fixed width: a bar takes the width of its parent, so a
                parent sized to its content (fit-content, hug) leaves it
                nothing. As a fit-content container it measured 0px. */}
            <nldd-container width="120px">
              <nldd-progress-bar
                value={completedCount}
                max={totalSteps}
                color="success"
                size="sm"
                value-text={`${completedCount}/${totalSteps}`}
              />
            </nldd-container>
          </nldd-container>

          {/* Stakeholders reference (recurring question) — only shown when stakeholders exist */}
          {stakeholderCount > 0 && (
            <nldd-inline-dialog
              icon="users"
              text="Wie zijn belanghebbenden?"
              horizontal-alignment="left"
            >
              <nldd-container layout="wrap" gap="8">
                <NlddActionText text={`${stakeholderCount} betrokkenen`} size="xs" onClick={onNavigateToStakeholders} />
                <nldd-link href={KCBR_STAKEHOLDERS_URL} target="_blank" accessible-label="Bekijk op KCBR" start-icon="external-link" size="xs" />
              </nldd-container>
            </nldd-inline-dialog>
          )}

          {/* Steps */}
          <nldd-list appearance="box-tinted" dividers="always">
            {steps.map((stepStatus) => (
              <BeleidskompasStepRow
                key={stepStatus.step.id}
                status={stepStatus}
                dossierId={nodeId}
                onCreateNew={(nodeType) => setCreateModalType(nodeType)}
                onLinkExisting={(nodeType) => setLinkModalType(nodeType)}
              />
            ))}
          </nldd-list>

          {/* Gap Analysis */}
          <nldd-divider />
          <GapAnalysisPanel dossierId={nodeId} />
        </nldd-container>
      </Card>

      {linkModalType && (
        <LinkExistingNodeModal
          open={!!linkModalType}
          onClose={() => setLinkModalType(null)}
          dossierId={nodeId}
          nodeType={linkModalType}
          excludeNodeIds={linkedNodeIds}
        />
      )}

      {createModalType && (
        <NodeCreateForm
          open={!!createModalType}
          onClose={() => setCreateModalType(null)}
          defaultNodeType={createModalType}
          linkToDossierId={nodeId}
        />
      )}
    </>
  );
}
