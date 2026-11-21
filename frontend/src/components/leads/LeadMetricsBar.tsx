import { useLeadMetrics } from '@/hooks/useLeads';
import { LEAD_STAGE_ORDER, LEAD_STAGE_LABELS } from '@/types';
import { stageTagColor } from './stageColors';

export function LeadMetricsBar({ initiatiefId }: { initiatiefId?: string }) {
  const { data: metrics } = useLeadMetrics(initiatiefId);

  if (!metrics) return null;

  return (
    <nldd-container layout="wrap" gap="8" vertical-alignment="center">
      <nldd-text size="sm" weight="medium">
        <p>{metrics.total} {metrics.total === 1 ? 'lead' : 'leads'}</p>
      </nldd-text>

      {LEAD_STAGE_ORDER.map((stage) => {
        const count = metrics.by_stage[stage] ?? 0;
        if (count === 0) return null;
        return (
          <nldd-tag key={stage} color={stageTagColor(stage)} size="sm" text={`${LEAD_STAGE_LABELS[stage]}: ${count}`} />
        );
      })}

      {metrics.stale_count > 0 && (
        <nldd-tag
          color="critical"
          size="sm"
          icon="exclamation-triangle"
          text={`${metrics.stale_count} inactief`}
        />
      )}
    </nldd-container>
  );
}
