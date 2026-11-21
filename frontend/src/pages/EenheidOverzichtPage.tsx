import { useState, useEffect, useMemo } from 'react';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { Card } from '@/components/common/Card';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { EmptyState } from '@/components/common/EmptyState';
import { Icon } from '@/components/nldd/Icon';
import { UnassignedTasksSection } from '@/components/eenheid/UnassignedTasksSection';
import { PersonTasksRow } from '@/components/eenheid/PersonTasksRow';
import { SubeenheidCard } from '@/components/eenheid/SubeenheidCard';
import { useOrganisatieFlat, useManagedEenheden } from '@/hooks/useOrganisatie';
import { useEenheidOverview } from '@/hooks/useTasks';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { formatOrganisatieType } from '@/types';

export function EenheidOverzichtPage() {
  const { currentPerson } = useCurrentPerson();
  const { data: managedEenheden } = useManagedEenheden(currentPerson?.id);
  const { data: eenheden } = useOrganisatieFlat();

  const [selectedEenheidId, setSelectedEenheidId] = useState<string>('');
  const [expandedPersonId, setExpandedPersonId] = useState<string | null>(null);

  const eenheidOptions = useMemo(
    () =>
      (eenheden ?? []).map((e) => ({
        value: e.id,
        label: e.naam,
        description: formatOrganisatieType(e.type),
      })),
    [eenheden],
  );

  // Auto-select managed unit on load
  useEffect(() => {
    if (selectedEenheidId) return;
    if (managedEenheden && managedEenheden.length > 0) {
      setSelectedEenheidId(managedEenheden[0].id);
    }
  }, [managedEenheden, selectedEenheidId]);

  const { data: overview, isLoading, isError } = useEenheidOverview(
    selectedEenheidId || null,
  );

  const handleSelectSubeenheid = (eenheidId: string) => {
    setSelectedEenheidId(eenheidId);
    setExpandedPersonId(null);
  };

  const handleTogglePerson = (personId: string) => {
    setExpandedPersonId((prev) => (prev === personId ? null : personId));
  };

  return (
    <nldd-container gap="24">
      {/* Org unit selector */}
      <nldd-container max-width="448px">
        <CreatableSelect
          label="Organisatie-eenheid"
          value={selectedEenheidId}
          onChange={setSelectedEenheidId}
          options={eenheidOptions}
          placeholder="Selecteer een eenheid..."
        />
      </nldd-container>

      {!selectedEenheidId && (
        <EmptyState
          icon="apartment-building"
          title="Selecteer een eenheid"
          description="Kies een organisatie-eenheid om het takenoverzicht te bekijken."
        />
      )}

      {selectedEenheidId && isLoading && (
        <nldd-container padding="32">
          <LoadingSpinner />
        </nldd-container>
      )}

      {selectedEenheidId && isError && (
        <nldd-banner
          variant="critical"
          size="sm"
          text="Kon het overzicht niet laden. Probeer het opnieuw."
        />
      )}

      {selectedEenheidId && overview && (
        <nldd-container gap="24">
          {/* Section 1: Onverdeeld */}
          <UnassignedTasksSection
            noUnitTasks={overview.unassigned_no_unit}
            noUnitCount={overview.unassigned_no_unit_count}
            noPersonTasks={overview.unassigned_no_person}
            noPersonCount={overview.unassigned_no_person_count}
            eenheidType={overview.eenheid_type}
            selectedEenheidId={selectedEenheidId}
          />

          {/* Section 2: Teamoverzicht */}
          <nldd-container gap="12">
            <nldd-container layout="row" gap="8" vertical-alignment="center">
              <Icon name="users" />
              <nldd-title size="display-5">
                <h2>Teamoverzicht</h2>
              </nldd-title>
            </nldd-container>
            {overview.by_person.length === 0 ? (
              <Card>
                <nldd-text color="secondary"><p>Geen personen in deze eenheid.</p></nldd-text>
              </Card>
            ) : (
              <nldd-table
                columns="minmax(200px,1fr) 100px 140px 100px 100px"
                sm-columns="minmax(0,1fr) 72px"
                accessible-label="Taken per persoon"
              >
                <nldd-table-row slot="header">
                  <nldd-text-cell text="Persoon" />
                  <nldd-text-cell text="Open" horizontal-alignment="right" hide-below="lg" />
                  <nldd-text-cell text="In uitvoering" horizontal-alignment="right" hide-below="lg" />
                  <nldd-text-cell text="Afgerond" horizontal-alignment="right" hide-below="lg" />
                  <nldd-text-cell text="Verlopen" horizontal-alignment="right" />
                </nldd-table-row>
                {overview.by_person.map((person) => (
                  <PersonTasksRow
                    key={person.person_id}
                    person={person}
                    isExpanded={expandedPersonId === person.person_id}
                    onToggle={() => handleTogglePerson(person.person_id)}
                  />
                ))}
              </nldd-table>
            )}
          </nldd-container>

          {/* Section 3: Subeenheden */}
          {overview.by_subeenheid.length > 0 && (
            <nldd-container gap="12">
              <nldd-container layout="row" gap="8" vertical-alignment="center">
                <Icon name="apartment-building" />
                <nldd-title size="display-5">
                  <h2>Subeenheden</h2>
                </nldd-title>
              </nldd-container>
              <nldd-container layout="grid" sm-column-count={2} lg-column-count={3} gap="12">
                {overview.by_subeenheid.map((sub) => (
                  <SubeenheidCard
                    key={sub.eenheid_id}
                    sub={sub}
                    onSelect={handleSelectSubeenheid}
                  />
                ))}
              </nldd-container>
            </nldd-container>
          )}
        </nldd-container>
      )}
    </nldd-container>
  );
}
