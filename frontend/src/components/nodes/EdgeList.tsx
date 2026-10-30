import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge } from '@/components/common/Badge';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Icon } from '@/components/nldd/Icon';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { useNlddEvent } from '@/components/nldd/events';
import { AddEdgeForm } from './AddEdgeForm';
import { useEdges, useDeleteEdge } from '@/hooks/useEdges';
import { NODE_TYPE_COLORS } from '@/types';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { useVocabulary } from '@/contexts/VocabularyContext';
import { NlddButton } from '@/components/nldd/NlddButton';

/** An `nldd-list-item-segment[button]` with its click bridged to React. */
function ClickableSegment({
  onClick,
  width,
  children,
}: {
  onClick: () => void;
  width?: 'fit-content' | 'full';
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', onClick);
  return (
    <nldd-list-item-segment ref={ref} button width={width}>
      {children}
    </nldd-list-item-segment>
  );
}

interface EdgeListProps {
  nodeId: string;
  nodeType?: string;
}

export function EdgeList({ nodeId, nodeType }: EdgeListProps) {
  const navigate = useNavigate();
  const { nodeLabel, nodeAltLabel, edgeLabel } = useVocabulary();
  const [showAddForm, setShowAddForm] = useState(false);
  const { data: edges = [], isLoading } = useEdges({ node_id: nodeId });
  const deleteEdge = useDeleteEdge();

  if (isLoading) {
    return <LoadingSpinner padding="32" />;
  }

  return (
    <nldd-container gap="16">
      <nldd-container layout="row" gap="8" vertical-alignment="center" horizontal-alignment="left">
        <nldd-title size={6}><h3>Verbindingen ({edges.length})</h3></nldd-title>
        <nldd-spacer direction="horizontal" size="flexible" />
        <NlddButton
          variant="secondary"
          size="sm"
          startIcon="plus"
          onClick={() => setShowAddForm(true)}
          text="Verbinding toevoegen"
        />
      </nldd-container>

      {edges.length > 0 ? (
        <nldd-list appearance="box-tinted" dividers="always">
          {edges.map((edge) => {
            const connectedNode =
              edge.from_node_id === nodeId ? edge.to_node : edge.from_node;
            const direction = edge.from_node_id === nodeId ? 'outgoing' : 'incoming';

            return (
              <nldd-list-item key={edge.id}>
                <ClickableSegment
                  width="full"
                  onClick={() => connectedNode && navigate(`/nodes/${connectedNode.id}`)}
                >
                  <nldd-title-cell
                    overline={edgeLabel(edge.edge_type_id)}
                    text={connectedNode?.title ?? ''}
                  >
                    <nldd-container slot="overline" layout="row" gap="8" vertical-alignment="center">
                      <Badge color="donkerblauw">{edgeLabel(edge.edge_type_id)}</Badge>
                      <Icon name={direction === 'incoming' ? 'arrow-left' : 'arrow-right'} size="xs" />
                    </nldd-container>
                    {connectedNode && (
                      <nldd-container layout="row" gap="8" vertical-alignment="center">
                        <Badge color={NODE_TYPE_COLORS[connectedNode.node_type]} title={nodeAltLabel(connectedNode.node_type)}>
                          {nodeLabel(connectedNode.node_type)}
                        </Badge>
                        {connectedNode.title}
                      </nldd-container>
                    )}
                  </nldd-title-cell>
                  {edge.description && (
                    <nldd-description-cell>
                      <RichTextDisplay content={edge.description} />
                    </nldd-description-cell>
                  )}
                </ClickableSegment>
                <nldd-list-item-segment width="fit-content">
                  <NlddIconButton
                    icon="trash"
                    variant="critical-transparent"
                    size="sm"
                    accessibleLabel="Verbinding verwijderen"
                    onClick={() => deleteEdge.mutate(edge.id)}
                  />
                </nldd-list-item-segment>
              </nldd-list-item>
            );
          })}
        </nldd-list>
      ) : (
        <EmptyState
          title="Geen verbindingen"
          description="Deze node heeft nog geen verbindingen met andere nodes."
          action={
            <NlddButton
              variant="secondary"
              size="sm"
              onClick={() => setShowAddForm(true)}
              text="Eerste verbinding toevoegen"
            />
          }
        />
      )}

      <AddEdgeForm
        open={showAddForm}
        onClose={() => setShowAddForm(false)}
        sourceNodeId={nodeId}
        sourceNodeType={nodeType}
      />
    </nldd-container>
  );
}
