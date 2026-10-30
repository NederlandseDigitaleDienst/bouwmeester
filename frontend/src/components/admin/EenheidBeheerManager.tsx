import { useRef, useState, useMemo } from 'react';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Select } from '@/components/common/Select';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { NlddButton } from '@/components/nldd/NlddButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { EmptyState } from '@/components/common/EmptyState';
import { useOrganisatieFlat } from '@/hooks/useOrganisatie';
import { usePermissions } from '@/hooks/usePermissions';
import {
  useInitiatieven,
  useInitiatievenForEenheid,
  useAddInitiatiefEenheid,
  useRemoveInitiatiefEenheid,
  useUpdateInitiatiefEenheidRol,
} from '@/hooks/useInitiatieven';
import {
  useEenheidModules,
  useAvailableModules,
  useUpdateEenheidModule,
} from '@/hooks/useEenheidModules';
import { formatOrganisatieType, INITIATIEF_ROL_LABELS } from '@/types';

const MODULE_DESCRIPTIONS: Record<string, string> = {
  corpus: 'Beleidsdossiers, doelen, instrumenten en hun relaties',
  initiatieven: 'Samenwerkingsinitiatieven met leden en eenheden',
  leads: 'Leads en contacten voor beleidsonderwerpen',
  opdrachten: 'Opdrachten en financieel overzicht',
  taken: 'Taakbeheer gekoppeld aan corpus-items',
};

const ROL_OPTIONS = Object.entries(INITIATIEF_ROL_LABELS).map(([value, label]) => ({
  value,
  label,
}));

export function EenheidBeheerManager() {
  const { data: organisatie = [], isLoading } = useOrganisatieFlat();
  const { managesEenheid } = usePermissions();
  // Module toggles need org:manage on the eenheid: only offer the ones this
  // person manages (everything for a super_admin).
  const allEenheden = useMemo(
    () => organisatie.filter((e) => managesEenheid(e.id)),
    [organisatie, managesEenheid],
  );
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const searchRef = useRef<HTMLElement>(null);

  useNlddEvent(searchRef, 'input', (e) => setSearch(eventValue(e)));

  const filtered = useMemo(() => {
    if (!search.trim()) return allEenheden;
    const q = search.toLowerCase();
    return allEenheden.filter(
      (e) =>
        e.naam.toLowerCase().includes(q) ||
        e.type.toLowerCase().includes(q),
    );
  }, [allEenheden, search]);

  if (isLoading) {
    return <LoadingSpinner padding="48" />;
  }

  return (
    <nldd-container gap="16">
      <nldd-text size="sm" color="secondary">
        Beheer initiatieven en modules per organisatie-eenheid. Klik op een eenheid om de details te
        zien.
      </nldd-text>

      <nldd-container max-width="448px">
        <nldd-text-field
          ref={searchRef}
          value={search}
          placeholder="Zoek op naam..."
          accessible-label="Zoek eenheid op naam"
        />
      </nldd-container>

      <nldd-table columns="minmax(200px,1fr) 160px" sm-columns="1fr" accessible-label="Organisatie-eenheden">
        <nldd-table-row slot="header">
          <nldd-text-cell text="Naam" />
          <nldd-text-cell text="Type" hide-below="md" />
        </nldd-table-row>
        {filtered.map((eenheid) => {
          const isExpanded = expandedId === eenheid.id;
          return (
            <EenheidRow
              key={eenheid.id}
              eenheid={eenheid}
              isExpanded={isExpanded}
              onToggle={() => setExpandedId(isExpanded ? null : eenheid.id)}
            />
          );
        })}
        <div slot="empty">
          <EmptyState
            icon="magnifier"
            title={search.trim() ? 'Geen eenheden gevonden' : 'Geen organisatie-eenheden beschikbaar'}
            description={search.trim() ? 'Pas je zoekopdracht aan.' : undefined}
          />
        </div>
      </nldd-table>
    </nldd-container>
  );
}

function EenheidRow({
  eenheid,
  isExpanded,
  onToggle,
}: {
  eenheid: { id: string; naam: string; type: string };
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const typeLabel = formatOrganisatieType(eenheid.type);

  return (
    <nldd-table-row>
      <nldd-text-cell>
        <NlddButton
          variant="neutral-transparent"
          size="sm"
          text={eenheid.naam}
          startIcon={isExpanded ? 'chevron-down' : 'chevron-right'}
          onClick={onToggle}
        />
      </nldd-text-cell>
      <nldd-text-cell text={typeLabel} color="secondary" hide-below="md" />
      {isExpanded && (
        <div style={{ gridColumn: '1 / -1' }}>
          <EenheidDetailPanel eenheidId={eenheid.id} />
        </div>
      )}
    </nldd-table-row>
  );
}

function EenheidDetailPanel({ eenheidId }: { eenheidId: string }) {
  const { data: initiatieven, isLoading: initiativeLoading } = useInitiatievenForEenheid(eenheidId);
  const { data: allInitiatieven } = useInitiatieven();
  const { data: moduleConfig, isLoading: modulesLoading } = useEenheidModules(eenheidId);
  const { data: moduleLabels } = useAvailableModules();
  const updateModuleMutation = useUpdateEenheidModule();
  const addEenheidMutation = useAddInitiatiefEenheid();
  const removeEenheidMutation = useRemoveInitiatiefEenheid();
  const updateRolMutation = useUpdateInitiatiefEenheidRol();

  const [addValue, setAddValue] = useState('');

  const availableInitiatieven = useMemo(() => {
    if (!allInitiatieven || !initiatieven) return [];
    const linkedIds = new Set(initiatieven.map((i) => i.initiatief_id));
    return allInitiatieven
      .filter((i) => !linkedIds.has(i.id))
      .map((i) => ({ value: i.id, label: i.naam }));
  }, [allInitiatieven, initiatieven]);

  const handleAddInitiatief = async (initiatiefId: string) => {
    if (!initiatiefId) return;
    try {
      await addEenheidMutation.mutateAsync({ initiatiefId, eenheidId });
      setAddValue('');
    } catch {
      // mutation.isError handles UI
    }
  };

  const handleRemoveInitiatief = async (initiatiefId: string) => {
    try {
      await removeEenheidMutation.mutateAsync({ initiatiefId, eenheidId });
    } catch {
      // mutation.isError handles UI
    }
  };

  const handleRolChange = async (initiatiefId: string, rol: string) => {
    try {
      await updateRolMutation.mutateAsync({ initiatiefId, eenheidId, rol });
    } catch {
      // mutation.isError handles UI
    }
  };

  const handleModuleToggle = async (module: string, currentEnabled: boolean) => {
    try {
      await updateModuleMutation.mutateAsync({
        eenheidId,
        module,
        enabled: !currentEnabled,
      });
    } catch {
      // error state handled by mutation
    }
  };

  return (
    <nldd-box>
      <nldd-container padding="20" gap="24">
      {/* Initiatieven */}
      <nldd-container gap="12">
        <nldd-container layout="row" gap="6" vertical-alignment="center">
          <nldd-icon icon="lightbulb" size="16" />
          <nldd-title size={6}><h3>Initiatieven</h3></nldd-title>
        </nldd-container>

        {initiativeLoading && <LoadingSpinner padding="16" />}

        {(addEenheidMutation.isError || removeEenheidMutation.isError || updateRolMutation.isError) && (
          <nldd-inline-dialog variant="alert" text="Kon initiatief-koppeling niet bijwerken." />
        )}

        {!initiativeLoading && initiatieven && initiatieven.length > 0 && (
          <nldd-list type="form" appearance="box-base" dividers="always" accessible-label="Gekoppelde initiatieven">
            {initiatieven.map((link) => (
              <InitiatiefRow
                key={link.initiatief_id}
                naam={link.initiatief_naam}
                rol={link.rol}
                onRolChange={(rol) => handleRolChange(link.initiatief_id, rol)}
                onRemove={() => handleRemoveInitiatief(link.initiatief_id)}
              />
            ))}
          </nldd-list>
        )}

        {!initiativeLoading && initiatieven && initiatieven.length === 0 && (
          <nldd-text size="sm" color="secondary">Geen gekoppelde initiatieven.</nldd-text>
        )}

        <nldd-container layout="row" gap="8" horizontal-alignment="left">
          <nldd-container max-width="320px">
            <CreatableSelect
              value={addValue}
              onChange={(val) => {
                setAddValue(val);
                if (val) handleAddInitiatief(val);
              }}
              options={availableInitiatieven}
              placeholder="Initiatief toevoegen..."
              emptyMessage="Geen initiatieven gevonden"
            />
          </nldd-container>
        </nldd-container>
      </nldd-container>

      {/* Modules */}
      <nldd-container gap="12">
        <nldd-container layout="row" gap="6" vertical-alignment="center">
          <nldd-icon icon="blocks-9" size="16" />
          <nldd-title size={6}><h3>Modules</h3></nldd-title>
        </nldd-container>

        {modulesLoading && <LoadingSpinner padding="16" />}

        {updateModuleMutation.isError && (
          <nldd-inline-dialog variant="alert" text="Kon module-instelling niet opslaan." />
        )}

        {!modulesLoading && moduleConfig && (
          <nldd-list type="form" appearance="box-base" dividers="always" accessible-label="Modules per eenheid">
            {moduleConfig.modules.map((mod) => {
              const isInherited = mod.inherited_from !== null && !mod.enabled;
              const label = moduleLabels?.[mod.module] ?? mod.module;
              const description = MODULE_DESCRIPTIONS[mod.module] ?? '';

              return (
                <ModuleRow
                  key={mod.module}
                  label={label}
                  description={description}
                  enabled={mod.enabled}
                  isInherited={isInherited}
                  inheritedFromNaam={mod.inherited_from_naam}
                  disabled={updateModuleMutation.isPending}
                  onToggle={() => handleModuleToggle(mod.module, mod.enabled)}
                />
              );
            })}
          </nldd-list>
        )}
      </nldd-container>
      </nldd-container>
    </nldd-box>
  );
}

function InitiatiefRow({
  naam,
  rol,
  onRolChange,
  onRemove,
}: {
  naam: string;
  rol: string;
  onRolChange: (rol: string) => void;
  onRemove: () => void;
}) {
  // Every control sits in a cell of its own. A bare nldd-dropdown in the row
  // stretches to fill it (that is its default without `width`), which on a
  // phone left the name cell one character wide: "RegelRecht" came out as a
  // column of letters. The dropdown gets a fixed width; the name takes the
  // rest and wraps as words.
  return (
    <nldd-list-item>
      <nldd-text-cell text={naam} />
      <nldd-cell width="fit-content">
        <Select
          size="sm"
          width="128px"
          aria-label={`Rol van ${naam}`}
          value={rol}
          onChange={(e) => onRolChange(e.target.value)}
          options={ROL_OPTIONS}
        />
      </nldd-cell>
      <nldd-cell width="fit-content">
        <NlddIconButton
          icon="close"
          accessibleLabel={`${naam} ontkoppelen`}
          variant="neutral-transparent"
          size="xs"
          onClick={onRemove}
        />
      </nldd-cell>
    </nldd-list-item>
  );
}

function ModuleRow({
  label,
  description,
  enabled,
  isInherited,
  inheritedFromNaam,
  disabled,
  onToggle,
}: {
  label: string;
  description: string;
  enabled: boolean;
  isInherited: boolean;
  inheritedFromNaam: string | null;
  disabled: boolean;
  onToggle: () => void;
}) {
  const switchRef = useRef<HTMLElement>(null);
  useNlddEvent(switchRef, 'change', onToggle);

  return (
    <nldd-list-item>
      <nldd-text-cell
        text={label}
        supporting-text={description || undefined}
        overline={isInherited ? `Overgenomen van ${inheritedFromNaam}` : undefined}
      />
      <nldd-cell width="fit-content">
        <nldd-switch
          ref={switchRef}
          checked={enabled ? true : undefined}
          disabled={isInherited || disabled ? true : undefined}
          accessible-label={`${label} inschakelen`}
        />
      </nldd-cell>
    </nldd-list-item>
  );
}
