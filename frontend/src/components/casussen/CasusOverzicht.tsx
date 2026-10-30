import { useState } from 'react';

import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { EmptyState } from '@/components/common/EmptyState';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import { useCasus } from '@/hooks/useCasussen';
import { useCasusFases } from '@/hooks/useCasusFases';
import { leadColumnTagColor } from '@/components/leads/stageColors';
import { CasusInfo } from './CasusInfo';
import { CasusSoortTags } from './CasusSoorten';
import { InitiatiefBacklog } from './InitiatiefBacklog';

interface Props {
  casusId: string;
  initiatiefId: string;
  /** Waar de filters van het werk komen: in de kop van de tab Casussen. */
  filterPlek?: HTMLElement | null;
}

/**
 * Eén casus, inline op de tab Casussen: een kop met fase, trekker en team,
 * de casusgegevens om uit te klappen, en daaronder het werk in hetzelfde
 * formaat als de backlog (issues met hun kanban), beperkt tot deze casus.
 *
 * Geen venster: taakdetail en issue bewerken openen er zelf een, en een
 * venster op een venster werkt niet prettig.
 */
export function CasusOverzicht({ casusId, initiatiefId, filterPlek }: Props) {
  const { data: casus, isLoading, isError } = useCasus(casusId);
  const fases = useCasusFases(initiatiefId);
  const fase = fases.find((f) => f.id === casus?.fase);
  const { openLeadDetail } = useLeadDetail();
  const [gegevensOpen, setGegevensOpen] = useState(false);

  if (isLoading) return <LoadingSpinner padding="32" />;
  if (isError || !casus) {
    return <EmptyState title="Casus niet gevonden" description="Kies een andere casus." />;
  }

  return (
    <nldd-container gap="8">
      <div
        style={{
          border: '1px solid var(--primitives-color-neutral-200)',
          borderRadius: 'var(--semantics-surfaces-corner-radius)',
          padding: '12px 16px',
        }}
      >
        <nldd-container gap="8">
          <nldd-container layout="row" gap="12" vertical-alignment="center">
            <nldd-title size={4} className="row-fill">
              <h3>{casus.title}</h3>
            </nldd-title>
            <NlddButton
              variant="neutral-transparent"
              size="sm"
              startIcon={gegevensOpen ? 'chevron-up' : 'chevron-down'}
              onClick={() => setGegevensOpen((v) => !v)}
              text={gegevensOpen ? 'Casusgegevens verbergen' : 'Casusgegevens'}
            />
            <NlddButton variant="neutral-transparent" size="sm" endIcon="arrow-right" onClick={() => openLeadDetail(casus.lead_id)} text="Lead" />
          </nldd-container>
          <nldd-container layout="wrap" gap="12" vertical-alignment="center">
            {fase ? (
              <nldd-tag text={fase.naam} color={leadColumnTagColor(fase.kleur)} size="sm" {...(fase.omschrijving ? { title: fase.omschrijving } : {})} />
            ) : (
              <nldd-tag text={casus.fase} color="neutral" size="sm" />
            )}
            <CasusSoortTags soorten={casus.soorten} />
            <nldd-text size="sm" color="secondary">
              {casus.trekker_naam ? `Trekker: ${casus.trekker_naam}` : 'Nog geen trekker'}
              {casus.team_count > 1 ? ` · ${casus.team_count - 1} teamleden` : ''}
            </nldd-text>
          </nldd-container>
          {gegevensOpen && (
            <div style={{ borderTop: '1px solid var(--primitives-color-neutral-200)', paddingTop: '12px' }}>
              <CasusInfo casus={casus} />
            </div>
          )}
        </nldd-container>
      </div>
      <InitiatiefBacklog initiatiefId={initiatiefId} vasteCasusId={casus.id} filterPlek={filterPlek} />
    </nldd-container>
  );
}
