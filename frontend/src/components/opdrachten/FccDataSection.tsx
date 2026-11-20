import { Badge } from '@/components/common/Badge';
import { DetailSection } from '@/components/common/DetailSection';
import { DetailMetadataGrid } from '@/components/common/DetailMetadataGrid';
import { Icon } from '@/components/nldd/Icon';
import {
  FCC_TRAFFIC_LIGHT_FIELDS,
  type FccTrafficLight,
} from '@/types';
import { formatCurrency } from '@/utils/format';

/** `FccTrafficLight` -> the design system's five semantic roles. */
const TRAFFIC_LIGHT_TAG_COLOR: Record<FccTrafficLight, 'success' | 'warning' | 'critical'> = {
  green: 'success',
  orange: 'warning',
  red: 'critical',
};

interface FccDataSectionProps {
  data: Record<string, unknown>;
  funnelfase?: string | null;
  afdeling?: string | null;
  portfolio?: string | null;
  labels?: string | null;
}

export function FccDataSection({
  data,
  funnelfase,
  afdeling,
  portfolio,
  labels,
}: FccDataSectionProps) {
  const trafficLights = FCC_TRAFFIC_LIGHT_FIELDS.map(({ key, label }) => ({
    label,
    value: data[key] as string | undefined,
  })).filter((tl) => tl.value);

  const labelList = labels
    ? labels.split(',').map((l) => l.trim()).filter(Boolean)
    : [];

  const metaItems: { label: string; value: string }[] = [];
  if (funnelfase) metaItems.push({ label: 'Funnelfase', value: funnelfase });
  if (afdeling) metaItems.push({ label: 'Afdeling', value: afdeling });
  const domein = data.PDD_Domein as string | undefined;
  if (domein && domein !== afdeling) metaItems.push({ label: 'Domein', value: domein });
  if (portfolio) metaItems.push({ label: 'Portfolio', value: portfolio });
  const fccType = data.Type as string | undefined;
  if (fccType) metaItems.push({ label: 'FCC Type', value: fccType });
  const fccStatus = data.Status as string | undefined;
  if (fccStatus) metaItems.push({ label: 'FCC Status', value: fccStatus });
  const eigenaar = data.Eigenaar as string | undefined;
  if (eigenaar) metaItems.push({ label: 'Eigenaar', value: eigenaar });
  const contactOpdrachtnemer = data.Contact_opdrachtnemer as string | undefined;
  if (contactOpdrachtnemer) metaItems.push({ label: 'Contact opdrachtnemer', value: contactOpdrachtnemer });
  const contactOpdrachtgever = data.Contactpersoon_opdrachtgever as string | undefined;
  if (contactOpdrachtgever) metaItems.push({ label: 'Contactpersoon opdrachtgever', value: contactOpdrachtgever });

  // Multi-year budget totals
  const budgetTotaal = data.Budget_totaal_ as number | undefined;
  const gerealiseerTotaal = data.Gerealiseerde_kosten_totaal_ as number | undefined;

  if (trafficLights.length === 0 && metaItems.length === 0 && labelList.length === 0) {
    return null;
  }

  return (
    <DetailSection
      title="Fortes Change Cloud"
      icon={<Icon name="cloud" size="sm" />}
      separated
    >
      <nldd-container gap="12">
        {/* Traffic lights */}
        {trafficLights.length > 0 && (
          <nldd-container layout="wrap" gap="12">
            {trafficLights.map(({ label, value }) => (
              <nldd-tag
                key={label}
                text={label}
                icon="circle-filled-extra-small"
                color={TRAFFIC_LIGHT_TAG_COLOR[value as FccTrafficLight] ?? 'neutral'}
                size="sm"
                title={`${label}: ${value}`}
              />
            ))}
          </nldd-container>
        )}

        {/* Metadata grid */}
        <DetailMetadataGrid items={metaItems} />

        {/* Labels */}
        {labelList.length > 0 && (
          <nldd-container layout="wrap" gap="6">
            {labelList.map((label) => (
              <Badge key={label} color="donkerblauw">
                {label}
              </Badge>
            ))}
          </nldd-container>
        )}

        {/* Multi-year totals */}
        {(budgetTotaal != null || gerealiseerTotaal != null) && (
          <nldd-container layout="row" gap="16">
            {budgetTotaal != null && (
              <nldd-text size="xs" color="secondary"><p>Budget totaal: {formatCurrency(budgetTotaal)}</p></nldd-text>
            )}
            {gerealiseerTotaal != null && (
              <nldd-text size="xs" color="secondary"><p>Gerealiseerd totaal: {formatCurrency(gerealiseerTotaal)}</p></nldd-text>
            )}
          </nldd-container>
        )}
      </nldd-container>
    </DetailSection>
  );
}
