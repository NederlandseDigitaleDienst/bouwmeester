import { useNavigate, useLocation } from 'react-router-dom';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { Icon } from '@/components/nldd/Icon';
import type { CorpusNode, NodeStatus } from '@/types';
import { NODE_TYPE_COLORS, NODE_STATUS_LABELS, NodeType } from '@/types';
import { useVocabulary } from '@/contexts/VocabularyContext';
import { richTextToPlain } from '@/utils/richtext';
import { formatDateShort } from '@/utils/dates';
import { formatCurrency, formatCurrencyCompact } from '@/utils/format';

interface NodeCardProps {
  node: CorpusNode;
}

export function NodeCard({ node }: NodeCardProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { nodeLabel, nodeAltLabel } = useVocabulary();
  const color = NODE_TYPE_COLORS[node.node_type];

  const kompasDone =
    node.beleidskompas_progress &&
    node.beleidskompas_progress.completed_steps === node.beleidskompas_progress.total_steps;

  return (
    <Card
      actionLabel={`Open ${node.title}`}
      onClick={() => navigate(`/nodes/${node.id}`, { state: { fromCorpus: location.pathname + location.search } })}
    >
      <nldd-container layout="row" gap="12" vertical-alignment="top">
        <nldd-container gap="4" min-width="0px">
          <nldd-container layout="row" gap="8" vertical-alignment="center">
            <Badge color={color} dot title={nodeAltLabel(node.node_type)}>
              {nodeLabel(node.node_type)}
            </Badge>
            {node.status && (
              <Badge color="coolgray">{NODE_STATUS_LABELS[node.status as NodeStatus] ?? node.status}</Badge>
            )}
          </nldd-container>

          {/* The title wraps rather than truncating: nldd-title resets its
              slotted heading with `all: revert !important`, so a truncate
              class on the h3 would never apply. */}
          <nldd-title size="display-6">
            <h3>{node.title}</h3>
          </nldd-title>

          {node.description && (
            <nldd-text size="xs" color="secondary" className="line-clamp-2">
              <p>{richTextToPlain(node.description)}</p>
            </nldd-text>
          )}
        </nldd-container>

        {/* Always visible: the whole card is a button, so the affordance does
            not need to wait for hover. Card never sets `group`, so
            `group-hover-reveal` here would hide the arrow at all times. */}
        <Icon name="arrow-right" size="md" className="shrink-0" />
      </nldd-container>

      {/* Footer info */}
      <nldd-container layout="row" gap="12" vertical-alignment="center" padding-top="12">
        {node.edge_count !== undefined && (
          <div className="hug">
            <Icon name="link" size="xs" />
            <nldd-text size="xs" color="secondary"><p>{node.edge_count} verbindingen</p></nldd-text>
          </div>
        )}
        {node.financieel_summary && node.financieel_summary.totaal_budget > 0 && (
          <div className="hug" title={`Budget: ${formatCurrency(node.financieel_summary.totaal_budget)} — Gerealiseerd: ${formatCurrency(node.financieel_summary.totaal_gerealiseerd)}`}>
            <Icon name="euro-sign" size="xs" />
            <nldd-text size="xs" color="secondary"><p>{formatCurrencyCompact(node.financieel_summary.totaal_budget)}</p></nldd-text>
          </div>
        )}
        {node.node_type === NodeType.DOSSIER && node.beleidskompas_progress && (
          <div className="hug" title={`Beleidskompas: ${node.beleidskompas_progress.completed_steps} van ${node.beleidskompas_progress.total_steps} stappen compleet`}>
            <Icon name="signpost" size="xs" />
            <nldd-text size="xs" weight="medium" color={kompasDone ? 'success' : 'secondary'}>
              <p>{node.beleidskompas_progress.completed_steps}/{node.beleidskompas_progress.total_steps}</p>
            </nldd-text>
          </div>
        )}
        <nldd-spacer direction="horizontal" size="flexible" />
        <nldd-text size="xs" color="secondary"><p>{formatDateShort(node.updated_at ?? node.created_at)}</p></nldd-text>
      </nldd-container>
    </Card>
  );
}
