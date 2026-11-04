import { useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { AiActionButton } from '@/components/common/AiActionButton';
import { suggestKompasLinks } from '@/api/llm';
import { apiPost } from '@/api/client';
import { Badge } from '@/components/common/Badge';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { useNlddEvent } from '@/components/nldd/events';
import { queryKeys } from '@/hooks/queryKeys';
import { NODE_TYPE_COLORS, type EdgeSuggestionItem, type NodeType } from '@/types';
import { useVocabulary } from '@/contexts/VocabularyContext';

/**
 * `nldd-icon-button` with a `loading` state: the shared `NlddIconButton`
 * wrapper does not expose it, so this uses the raw element directly for the
 * one row action that needs a busy spinner while the edge is being created.
 */
function ApproveButton({ loading, onClick }: { loading: boolean; onClick: () => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', onClick);
  return (
    <nldd-icon-button
      ref={ref}
      icon="check-mark"
      appearance="neutral-transparent"
      size="sm"
      accessible-label="Koppelen"
      loading={loading ? true : undefined}
    />
  );
}

interface KompasStepSuggestionsProps {
  dossierId: string;
  stepNodeTypes: NodeType[];
  stepDescription: string;
}

export function KompasStepSuggestions({
  dossierId,
  stepNodeTypes,
  stepDescription,
}: KompasStepSuggestionsProps) {
  const queryClient = useQueryClient();
  const { nodeLabel } = useVocabulary();
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<EdgeSuggestionItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approved, setApproved] = useState<Set<string>>(new Set());
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  const [approving, setApproving] = useState<Set<string>>(new Set());

  const handleSuggest = async () => {
    setLoading(true);
    setError(null);
    setSuggestions(null);
    setApproved(new Set());
    setRejected(new Set());
    try {
      const res = await suggestKompasLinks(dossierId, stepNodeTypes, stepDescription);
      if (!res.available) {
        setError('AI-suggesties zijn niet beschikbaar.');
        return;
      }
      setSuggestions(res.suggestions);
    } catch {
      setError('Fout bij ophalen van suggesties.');
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (s: EdgeSuggestionItem) => {
    setApproving((prev) => new Set([...prev, s.target_node_id]));
    try {
      await apiPost('/api/edges', {
        from_node_id: s.target_node_id,
        to_node_id: dossierId,
        edge_type_id: 'onderdeel_van',
        description: s.reason,
      });
      setApproved((prev) => new Set([...prev, s.target_node_id]));
      // Invalidate graph queries to refresh Beleidskompas
      await queryClient.invalidateQueries({ queryKey: queryKeys.nodes.graph(dossierId, 1) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.nodes.neighbors(dossierId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.edges.all });
    } catch {
      setError('Fout bij aanmaken van relatie.');
    } finally {
      setApproving((prev) => {
        const next = new Set(prev);
        next.delete(s.target_node_id);
        return next;
      });
    }
  };

  return (
    <nldd-container gap="8">
      <AiActionButton
        label="Aanbevolen koppelingen"
        loading={loading}
        onClick={handleSuggest}
        compact
      />

      {error && <nldd-text size="xs" color="critical">{error}</nldd-text>}

      {suggestions !== null && suggestions.length === 0 && (
        <nldd-text size="xs" color="secondary">Geen suggesties gevonden.</nldd-text>
      )}

      {suggestions && suggestions.length > 0 && (
        <nldd-list appearance="box-tinted" dividers="always">
          {suggestions.map((s) => {
            const isApproved = approved.has(s.target_node_id);
            const isRejected = rejected.has(s.target_node_id);

            return (
              <nldd-list-item key={s.target_node_id}>
                <nldd-text-cell width="fit-content">
                  <Badge color={NODE_TYPE_COLORS[s.target_node_type as NodeType]} dot>
                    {nodeLabel(s.target_node_type)}
                  </Badge>
                </nldd-text-cell>
                <nldd-text-cell
                  text={s.target_node_title}
                  overline={`${Math.round(s.confidence * 100)}%`}
                  color={isRejected ? 'secondary' : 'content'}
                />
                {!isApproved && !isRejected && (
                  <>
                    <ApproveButton
                      loading={approving.has(s.target_node_id)}
                      onClick={() => handleApprove(s)}
                    />
                    <NlddIconButton
                      icon="close"
                      variant="neutral-transparent"
                      size="sm"
                      accessibleLabel="Afwijzen"
                      onClick={() => setRejected((prev) => new Set([...prev, s.target_node_id]))}
                    />
                  </>
                )}
                {isApproved && <nldd-tag text="Gekoppeld" color="success" size="sm" />}
                {isRejected && <nldd-tag text="Afgewezen" color="neutral" size="sm" />}
              </nldd-list-item>
            );
          })}
        </nldd-list>
      )}
    </nldd-container>
  );
}
