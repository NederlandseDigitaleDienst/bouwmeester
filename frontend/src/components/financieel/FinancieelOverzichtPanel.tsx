import { useNodeFinancieel, useNodeOpdrachten } from '@/hooks/useOpdrachten';
import {
  OPDRACHT_STATUS_LABELS,
  OPDRACHT_STATUS_COLORS,
  OpdrachtStatus,
} from '@/types';
import { Badge } from '@/components/common/Badge';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { formatCurrencyCompact, calculateUtilization } from '@/utils/format';
import { useOpdrachtDetail } from '@/contexts/OpdrachtDetailContext';
import { useOpdrachtCreate } from '@/contexts/OpdrachtCreateContext';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddListItemButton } from '@/components/nldd/NlddLink';

interface FinancieelOverzichtPanelProps {
  nodeId: string;
  nodeType: string;
}

export function FinancieelOverzichtPanel({ nodeId, nodeType }: FinancieelOverzichtPanelProps) {
  const { data: overzicht, isLoading: loadingOverzicht } = useNodeFinancieel(nodeId);
  const { data: opdrachten = [], isLoading: loadingOpdrachten } = useNodeOpdrachten(nodeId);
  const { openOpdrachtDetail } = useOpdrachtDetail();
  const { openOpdrachtCreate } = useOpdrachtCreate();

  if (loadingOverzicht || loadingOpdrachten) {
    return <LoadingSpinner text="Laden..." />;
  }

  if (!overzicht || overzicht.per_jaar.length === 0) {
    return (
      <nldd-inline-dialog icon="euro-sign" text="Geen financiële gegevens beschikbaar." />
    );
  }

  return (
    <nldd-container gap="16">
      {/* Summary */}
      <nldd-collection layout="grid" item-min-width="160px" gap="12">
        <nldd-card background="tinted">
          <nldd-container padding="12" gap="2">
            <nldd-text size="xs" color="secondary">Totaal budget</nldd-text>
            <nldd-text size="lg" weight="bold">{formatCurrencyCompact(overzicht.totaal_budget)}</nldd-text>
          </nldd-container>
        </nldd-card>
        <nldd-card background="tinted">
          <nldd-container padding="12" gap="2">
            <nldd-text size="xs" color="secondary">Totaal gerealiseerd</nldd-text>
            <nldd-text size="lg" weight="bold">{formatCurrencyCompact(overzicht.totaal_gerealiseerd)}</nldd-text>
          </nldd-container>
        </nldd-card>
        <nldd-card background="tinted">
          <nldd-container padding="12" gap="2">
            <nldd-text size="xs" color="secondary">Uitnutting</nldd-text>
            <nldd-text size="lg" weight="bold">
              {overzicht.uitnutting_percentage != null ? `${overzicht.uitnutting_percentage.toFixed(1)}%` : '-'}
            </nldd-text>
            {overzicht.uitnutting_percentage != null && (
              <nldd-progress-bar
                value={Math.min(overzicht.uitnutting_percentage, 100)}
                max={100}
                size="sm"
                value-display="none"
              />
            )}
          </nldd-container>
        </nldd-card>
      </nldd-collection>

      {/* Per year breakdown */}
      <nldd-container gap="8">
        <nldd-title size={6}><h4>Per begrotingsjaar</h4></nldd-title>
        <nldd-table
          columns="minmax(80px,1fr) minmax(100px,1fr) minmax(100px,1fr) minmax(100px,1fr) minmax(100px,1fr)"
          accessible-label="Financieel overzicht per begrotingsjaar"
        >
          <nldd-table-row slot="header">
            <nldd-text-cell text="Jaar" />
            <nldd-text-cell text="Budget" horizontal-alignment="right" />
            <nldd-text-cell text="Gerealiseerd" horizontal-alignment="right" />
            <nldd-text-cell text="Uitnutting" horizontal-alignment="right" />
            <nldd-text-cell text="Opdrachten" horizontal-alignment="right" />
          </nldd-table-row>
          {overzicht.per_jaar.map((j) => {
            const uitn = calculateUtilization(j.budget, j.gerealiseerd);
            return (
              <nldd-table-row key={j.begrotingsjaar}>
                <nldd-text-cell text={String(j.begrotingsjaar)} />
                <nldd-text-cell text={formatCurrencyCompact(j.budget)} horizontal-alignment="right" />
                <nldd-text-cell text={formatCurrencyCompact(j.gerealiseerd)} horizontal-alignment="right" />
                <nldd-text-cell text={uitn != null ? `${uitn.toFixed(1)}%` : '-'} horizontal-alignment="right" />
                <nldd-text-cell text={String(j.opdracht_count)} color="secondary" horizontal-alignment="right" />
              </nldd-table-row>
            );
          })}
        </nldd-table>
      </nldd-container>

      {/* Opdrachten list */}
      <nldd-container gap="8">
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <nldd-title size={6}><h4>Opdrachten</h4></nldd-title>
          <nldd-spacer direction="horizontal" size="flexible" />
          {nodeType === 'instrument' && (
            <NlddButton
              variant="secondary"
              size="sm"
              startIcon="plus"
              onClick={() => openOpdrachtCreate({ instrument_id: nodeId })}
              text="Nieuwe opdracht"
            />
          )}
        </nldd-container>
        {opdrachten.length > 0 ? (
          <nldd-list appearance="box-tinted" dividers="always">
            {opdrachten.map((o) => (
              <NlddListItemButton key={o.id} onClick={() => openOpdrachtDetail(o.id)}>
                <nldd-title-cell
                  text={o.titel}
                  overline={`${o.begrotingsjaar} · ${o.opdrachtnemer?.afkorting || o.opdrachtnemer?.naam || '-'}`}
                />
                <nldd-text-cell width="fit-content" text={formatCurrencyCompact(o.budget)} />
                <nldd-text-cell width="fit-content">
                  <Badge color={OPDRACHT_STATUS_COLORS[o.status as OpdrachtStatus] || 'coolgray'}>
                    {OPDRACHT_STATUS_LABELS[o.status as OpdrachtStatus] || o.status}
                  </Badge>
                </nldd-text-cell>
              </NlddListItemButton>
            ))}
          </nldd-list>
        ) : (
          <nldd-text size="sm" color="secondary">Nog geen opdrachten voor dit instrument.</nldd-text>
        )}
      </nldd-container>
    </nldd-container>
  );
}
