import { useCallback, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { Badge } from '@/components/common/Badge';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { ViewToggle } from '@/components/common/ViewToggle';
import { eventValue, orUndef, useNlddEvent } from '@/components/nldd/events';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddListItemButton } from '@/components/nldd/NlddLink';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { useInitiatiefPersonen } from '@/hooks/useInitiatieven';
import { useInitiatiefCirkel, useInitiatiefRollen } from '@/hooks/useInitiatiefRollen';
import { ROL_STATUS_LABELS } from '@/types';
import type { InitiatiefDetail, InitiatiefRol } from '@/types';
import { CirkelKaart } from './CirkelKaart';
import { CirkelPaneel } from './CirkelPaneel';
import { PersoonWerkScherm } from './PersoonWerkScherm';
import { RolPaneel } from './RolPaneel';
import { filterRollen, isBelegd, isOpen, type RollenFilter } from './rollenFilter';

type Weergave = 'cirkel' | 'lijst';

/**
 * De rollen van een initiatief: de cirkel (standaard) of een lijst, en per
 * persoon wat die draagt. Wat open staat, zit in de URL: `?rol=` voor het
 * zijpaneel van een rol, `?persoon=` voor de persoonspagina, `?weergave=lijst`.
 */
export function InitiatiefRollen({ initiatief }: { initiatief: InitiatiefDetail }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const persoonId = searchParams.get('persoon');
  const rolId = searchParams.get('rol');
  const canEdit = initiatief.access_level === 'eigenaar' || initiatief.access_level === 'contributor';
  const { data: rollen = [], isLoading } = useInitiatiefRollen(initiatief.id);
  const [nieuw, setNieuw] = useState(false);

  const zet = useCallback(
    (sleutel: string, waarde: string | null) => {
      setSearchParams((prev) => {
        const p = new URLSearchParams(prev);
        if (waarde) p.set(sleutel, waarde);
        else p.delete(sleutel);
        return p;
      });
    },
    [setSearchParams],
  );

  const paneel = (
    <RolPaneel
      initiatief={initiatief}
      rollen={rollen}
      rol={rollen.find((r) => r.id === rolId) ?? null}
      nieuw={nieuw}
      canEdit={canEdit}
      onClose={() => {
        setNieuw(false);
        zet('rol', null);
      }}
      onKiesRol={(id) => {
        setNieuw(false);
        zet('rol', id);
      }}
    />
  );

  if (persoonId) {
    return (
      <>
        <PersoonWerkScherm
          initiatief={initiatief}
          personId={persoonId}
          canEdit={canEdit}
          onTerug={() => zet('persoon', null)}
          onKiesRol={(id) => zet('rol', id)}
        />
        {paneel}
      </>
    );
  }

  if (isLoading) {
    return (
      <nldd-container layout="row" horizontal-alignment="center" padding="48">
        <LoadingSpinner />
      </nldd-container>
    );
  }

  return (
    <>
      <RollenOverzicht
        initiatief={initiatief}
        rollen={rollen}
        canEdit={canEdit}
        weergave={searchParams.get('weergave') === 'lijst' ? 'lijst' : 'cirkel'}
        gekozen={rolId}
        onWeergave={(w) => zet('weergave', w === 'lijst' ? 'lijst' : null)}
        onKiesRol={(id) => zet('rol', id)}
        onKiesPersoon={(id) => zet('persoon', id)}
        onNieuw={() => setNieuw(true)}
      />
      {paneel}
    </>
  );
}

function RollenOverzicht({
  initiatief,
  rollen,
  canEdit,
  weergave,
  gekozen,
  onWeergave,
  onKiesRol,
  onKiesPersoon,
  onNieuw,
}: {
  initiatief: InitiatiefDetail;
  rollen: InitiatiefRol[];
  canEdit: boolean;
  weergave: Weergave;
  gekozen: string | null;
  onWeergave: (w: Weergave) => void;
  onKiesRol: (id: string) => void;
  onKiesPersoon: (id: string) => void;
  onNieuw: () => void;
}) {
  const { data: cirkel } = useInitiatiefCirkel(initiatief.id);
  const { data: personen } = useInitiatiefPersonen(initiatief.id);
  const { currentPerson } = useCurrentPerson();
  const [zoek, setZoek] = useState('');
  const [filter, setFilter] = useState<RollenFilter>('alle');
  const [cirkelOpen, setCirkelOpen] = useState(false);

  const zichtbaar = useMemo(
    () => filterRollen(rollen, zoek, filter, currentPerson?.id ?? null),
    [rollen, zoek, filter, currentPerson?.id],
  );
  const zichtbaarIds = useMemo(() => new Set(zichtbaar.map((r) => r.id)), [zichtbaar]);
  const open = rollen.filter(isOpen).length;
  const team = (personen ?? []).filter((p) => !p.is_agent);
  const rollenPerPersoon = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const r of rollen) {
      if (!r.vervuller || r.status !== 'belegd') continue;
      m.set(r.vervuller.id, [...(m.get(r.vervuller.id) ?? []), r.naam]);
    }
    return m;
  }, [rollen]);

  return (
    <nldd-container gap="24">
      <nldd-container gap="12">
        <nldd-container layout="wrap" gap="8" vertical-alignment="center">
          <nldd-container width="fit-content" className="row-fill">
            <ZoekVeld value={zoek} onChange={setZoek} />
          </nldd-container>
          <ViewToggle<Weergave>
            value={weergave}
            onChange={onWeergave}
            accessibleLabel="Weergave"
            options={[
              { value: 'cirkel', label: 'Cirkel', icon: 'circle' },
              { value: 'lijst', label: 'Lijst', icon: 'list' },
            ]}
          />
          {canEdit && <NlddButton size="sm" startIcon="plus" onClick={onNieuw} text="Rol toevoegen" />}
        </nldd-container>
        <FilterKeuze value={filter} onChange={setFilter} alle={rollen.length} open={open} />
      </nldd-container>

      {rollen.length === 0 ? (
        <EmptyState
          icon="person-text-rectangle"
          title="Nog geen rollen"
          description="Beschrijf een rol met een doel, waarop hij aanspreekbaar is en waar hij over gaat. Alleen waar iets op deze manier geregeld moet worden."
          action={canEdit ? <NlddButton size="sm" onClick={onNieuw} text="Eerste rol toevoegen" /> : undefined}
        />
      ) : weergave === 'cirkel' ? (
        <CirkelKaart
          cirkel={cirkel}
          rollen={rollen}
          zichtbaar={zichtbaarIds}
          gekozen={gekozen}
          onKies={onKiesRol}
          onKiesCirkel={() => setCirkelOpen(true)}
        />
      ) : zichtbaar.length === 0 ? (
        <nldd-text size="sm" color="secondary">Geen rollen gevonden.</nldd-text>
      ) : (
        <nldd-list type="list" appearance="box-tinted" accessible-label="Rollen">
          {zichtbaar.map((rol) => (
            <NlddListItemButton key={rol.id} onClick={() => onKiesRol(rol.id)}>
              <nldd-container layout="row" width="full" gap="8" vertical-alignment="center">
                <nldd-text-cell text={rol.naam} supporting-text={rol.doel || undefined} width="full" />
                <div className="hug">
                  <RolStatus rol={rol} />
                </div>
              </nldd-container>
            </NlddListItemButton>
          ))}
        </nldd-list>
      )}

      <nldd-container gap="8">
        <nldd-title size={6}>Per persoon</nldd-title>
        <nldd-text size="xs" color="secondary">
          Kies iemand om de focus, rollen, interesse, leads, casussen, onderzoeksvragen en open taken te zien.
        </nldd-text>
        {team.length === 0 ? (
          <nldd-text size="sm" color="secondary">Nog niemand kan dit initiatief zien.</nldd-text>
        ) : (
          <nldd-list type="list" appearance="box-tinted" accessible-label="Mensen in dit initiatief">
            {team.map((p) => {
              const namen = rollenPerPersoon.get(p.id) ?? [];
              return (
                <NlddListItemButton key={p.id} onClick={() => onKiesPersoon(p.id)}>
                  <nldd-text-cell text={p.naam} supporting-text={namen.length ? namen.join(', ') : 'Geen rol'} width="full" />
                </NlddListItemButton>
              );
            })}
          </nldd-list>
        )}
      </nldd-container>

      {cirkelOpen && cirkel && (
        <CirkelPaneel initiatiefId={initiatief.id} cirkel={cirkel} canEdit={canEdit} onClose={() => setCirkelOpen(false)} />
      )}
    </nldd-container>
  );
}

/** Alle, Van mij, en Open als laatste, met het telbolletje op zijn hoek. */
function FilterKeuze({
  value,
  onChange,
  alle,
  open,
}: {
  value: RollenFilter;
  onChange: (v: RollenFilter) => void;
  alle: number;
  open: number;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(
    ref,
    'change',
    useCallback(
      (e: Event) => {
        const v = eventValue(e);
        if (v === 'alle' || v === 'open' || v === 'mijn') onChange(v);
      },
      [onChange],
    ),
  );
  return (
    <div className="rollen-filter">
      <nldd-segmented-control ref={ref} type="radio" size="sm" value={value} accessible-label="Welke rollen">
        <nldd-segmented-control-item value="alle" text={`Alle (${alle})`} selected={orUndef(value === 'alle')} />
        <nldd-segmented-control-item value="mijn" text="Van mij" selected={orUndef(value === 'mijn')} />
        <nldd-segmented-control-item value="open" text="Open" selected={orUndef(value === 'open')} />
      </nldd-segmented-control>
      {open > 0 && (
        <>
          <span className="rollen-filter-teller" aria-hidden="true">
            <nldd-badge number={open} size="sm" color="critical" />
          </span>
          <span className="visually-hidden">{`${open} ${open === 1 ? 'rol staat' : 'rollen staan'} open`}</span>
        </>
      )}
    </div>
  );
}

function RolStatus({ rol }: { rol: InitiatiefRol }) {
  return (
    <>
      {rol.vervuller && rol.status === 'belegd' && !rol.vervuller_is_lid ? (
        <Badge color="rood" title="De vervuller kan dit initiatief niet meer zien">
          {`${rol.vervuller.naam}, geen toegang`}
        </Badge>
      ) : isBelegd(rol) && rol.vervuller ? (
        <Badge color="paars">{rol.vervuller.naam}</Badge>
      ) : (
        <Badge color={rol.status === 'open' ? 'oranje' : 'coolgray'}>{ROL_STATUS_LABELS[rol.status]}</Badge>
      )}
      {rol.interesse.length > 0 && <Badge color="mosgroen">{`${rol.interesse.length} interesse`}</Badge>}
    </>
  );
}

function ZoekVeld({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));
  return (
    <nldd-search-field ref={ref} value={value} placeholder="Zoek op rol, domein of persoon" accessible-label="Zoek in rollen" />
  );
}
