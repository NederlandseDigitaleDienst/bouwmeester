import { useRef, useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Modal } from '@/components/common/Modal';
import { Badge } from '@/components/common/Badge';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { useNodes } from '@/hooks/useNodes';
import { createEdge } from '@/api/edges';
import { queryKeys } from '@/hooks/queryKeys';
import { NODE_TYPE_LABELS, NODE_TYPE_COLORS, type NodeType } from '@/types';
import { useToast } from '@/contexts/ToastContext';
import { EDGE_TYPE_ONDERDEEL_VAN } from './constants';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddListItemButton } from '@/components/nldd/NlddLink';

interface LinkExistingNodeModalProps {
  open: boolean;
  onClose: () => void;
  dossierId: string;
  nodeType: NodeType;
  excludeNodeIds?: Set<string>;
}

export function LinkExistingNodeModal({ open, onClose, dossierId, nodeType, excludeNodeIds }: LinkExistingNodeModalProps) {
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [isLinking, setIsLinking] = useState(false);
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const searchRef = useRef<HTMLElement>(null);
  useNlddEvent(searchRef, 'input', (e) => setSearch(eventValue(e)));

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Server-side filtered query, excluding already-linked nodes (min 2 chars to avoid overly broad queries)
  const searchQuery = debouncedSearch.length >= 2 ? debouncedSearch : undefined;
  const { data: nodes, isLoading } = useNodes(nodeType, searchQuery);
  const filteredNodes = (nodes ?? []).filter((n) => !excludeNodeIds?.has(n.id));

  const handleLink = async (targetNodeId: string) => {
    setIsLinking(true);
    try {
      await createEdge({
        from_node_id: targetNodeId,
        to_node_id: dossierId,
        edge_type_id: EDGE_TYPE_ONDERDEEL_VAN,
      });
      await queryClient.invalidateQueries({ queryKey: queryKeys.nodes.graph(dossierId, 2) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.nodes.neighbors(dossierId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.edges.all });
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Onbekende fout';
      showError(`Koppelen mislukt: ${msg}`);
    } finally {
      setIsLinking(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`${NODE_TYPE_LABELS[nodeType]} koppelen aan dossier`}
      footer={
        <NlddButton variant="secondary" onClick={onClose} text="Annuleren" />
      }
    >
      <nldd-container gap="16">
        {/* De placeholder verdwijnt zodra er een waarde staat, dus die is geen
            toegankelijke naam. */}
        <nldd-search-field
          ref={searchRef}
          value={search}
          placeholder={`Zoek ${NODE_TYPE_LABELS[nodeType].toLowerCase()}...`}
          accessible-label={`Zoek ${NODE_TYPE_LABELS[nodeType].toLowerCase()}`}
        />

        {isLoading ? (
          <nldd-inline-dialog variant="loading" text="Laden..." />
        ) : filteredNodes.length === 0 ? (
          <nldd-inline-dialog
            icon="question-mark-circle"
            text={`Geen ${NODE_TYPE_LABELS[nodeType].toLowerCase()} gevonden.`}
          />
        ) : (
          // No nldd-container attribute caps height with a scrollbar, so this
          // is an inline style.
          <div style={{ maxHeight: '18rem', overflowY: 'auto' }}>
            <nldd-list appearance="box-tinted" dividers="always">
              {filteredNodes.map((node) => (
                <NlddListItemButton key={node.id} disabled={isLinking} onClick={() => handleLink(node.id)}>
                  <nldd-text-cell width="fit-content">
                    <Badge color={NODE_TYPE_COLORS[nodeType]} dot>
                      {NODE_TYPE_LABELS[nodeType]}
                    </Badge>
                  </nldd-text-cell>
                  <nldd-text-cell text={node.title} />
                </NlddListItemButton>
              ))}
            </nldd-list>
          </div>
        )}
      </nldd-container>
    </Modal>
  );
}
