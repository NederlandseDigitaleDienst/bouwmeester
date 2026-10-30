import { useCallback, useRef, useState, useMemo, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useOpdrachten, useOpdrachtenSummary, useMatchOpdrachtContactsBulk } from '@/hooks/useOpdrachten';
import { useOrganisatieFlat } from '@/hooks/useOrganisatie';
import { usePeople } from '@/hooks/usePeople';
import { useNodes } from '@/hooks/useNodes';
import { useTriggerFccSync, useFccSchema, useLastFccSync } from '@/hooks/useFcc';
import { useOpdrachtDetail } from '@/contexts/OpdrachtDetailContext';
import { useOpdrachtCreate } from '@/contexts/OpdrachtCreateContext';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { usePermissions } from '@/hooks/usePermissions';
import { MultiSelect } from '@/components/common/MultiSelect';
import type { MultiSelectOption } from '@/components/common/MultiSelect';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import type { SelectOption } from '@/components/common/CreatableSelect';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { useDebounce } from '@/hooks/useDebounce';
import {
  OPDRACHT_TYPE_LABELS,
  OPDRACHT_STATUS_LABELS,
  OPDRACHT_STATUS_COLORS,
  OPDRACHT_TYPE_COLORS,
  FCC_TRAFFIC_LIGHT_COLORS,
  FCC_TRAFFIC_LIGHT_FIELDS,
  NodeType,
  type FccTrafficLight,
  type Opdracht,
  type OpdrachtFilters,
  OpdrachtType,
  OpdrachtStatus,
} from '@/types';
import { Badge } from '@/components/common/Badge';
import { formatCurrency, formatCurrencyCompact } from '@/utils/format';
import { timeAgo } from '@/utils/dates';
import { NlddButton } from '@/components/nldd/NlddButton';

const MY_OPDRACHTEN_SENTINEL = '__me__';

/** The opdrachten search field: `nldd-search-field` with its `input` event bridged to React. */
function OpdrachtenSearchField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));
  return (
    <nldd-search-field
      ref={ref}
      value={value}
      placeholder="Zoek opdrachten..."
      accessible-label="Zoek opdrachten"
    />
  );
}

/**
 * Shows or hides the filters on a phone. Six filters stacked there took half
 * the screen before the first opdracht, so below `sm` they stay folded away
 * until asked for; the count says whether any of them is narrowing the list.
 */
function FiltersToggle({
  activeCount,
  onChange,
}: {
  activeCount: number;
  onChange: (open: boolean) => void;
}) {
  // A toggle button, which announces its state in both positions
  // (aria-pressed true/false). nldd-button's `expanded` only ever wrote
  // aria-expanded="true": closed, the attribute was absent, and aria-controls
  // on the host never reached the button inside the shadow root.
  //
  // Uncontrolled on purpose: the button keeps its own state and reports it.
  // Driving `selected` from React left aria-pressed="" (neither true nor
  // false) once the attribute was removed again.
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', (e) =>
    onChange(Boolean((e as CustomEvent<{ selected?: boolean }>).detail?.selected)),
  );
  return (
    <nldd-toggle-button
      ref={ref}
      size="sm"
      icon="filter"
      text={activeCount > 0 ? `Filters (${activeCount})` : 'Filters'}
    />
  );
}

const TYPE_OPTIONS: MultiSelectOption[] = Object.entries(OPDRACHT_TYPE_LABELS).map(
  ([value, label]) => ({ value, label }),
);

const STATUS_OPTIONS: MultiSelectOption[] = Object.entries(OPDRACHT_STATUS_LABELS).map(
  ([value, label]) => ({ value, label }),
);

/** FCC "traffic light" dots. Green, orange and red carry their usual meaning,
 * so `FCC_TRAFFIC_LIGHT_COLORS` (src/types) yields a design-system color token
 * per value and the dot paints from it directly. Anything that is not a real
 * custom property leaves the dot invisible, with only its title attribute to
 * give it away. */
function FccTrafficLights({ opdracht }: { opdracht: Opdracht }) {
  if (!opdracht.fcc_raw_data) return null;
  return (
    <nldd-container layout="row" gap="2" title="FCC stoplichten">
      {FCC_TRAFFIC_LIGHT_FIELDS.map(({ key, label }) => {
        const val = (opdracht.fcc_raw_data as Record<string, unknown>)?.[key] as string | undefined;
        return val ? (
          <span
            key={key}
            style={{
              display: 'inline-block',
              width: '8px',
              height: '8px',
              borderRadius: '9999px',
              background:
                FCC_TRAFFIC_LIGHT_COLORS[val as FccTrafficLight] ??
                'var(--primitives-color-neutral-300)',
            }}
            title={`${label}: ${val}`}
          />
        ) : null;
      })}
    </nldd-container>
  );
}

/** One opdracht row in the desktop table. The title cell carries the click. */
function OpdrachtRow({ opdracht: o, onOpen }: { opdracht: Opdracht; onOpen: () => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', useCallback(() => onOpen(), [onOpen]));

  return (
    <nldd-table-row>
      <nldd-title-cell ref={ref} text={o.titel} style={{ cursor: 'pointer' }} />
      <nldd-text-cell>
        <Badge color={OPDRACHT_TYPE_COLORS[o.type as OpdrachtType] || 'coolgray'}>
          {OPDRACHT_TYPE_LABELS[o.type as OpdrachtType] || o.type}
        </Badge>
      </nldd-text-cell>
      <nldd-text-cell text={String(o.begrotingsjaar)} />
      <nldd-text-cell text={o.opdrachtnemer?.afkorting || o.opdrachtnemer?.naam || '-'} />
      <nldd-text-cell text={o.instrument?.title || '-'} />
      <nldd-text-cell text={formatCurrency(o.budget)} horizontal-alignment="right" />
      <nldd-text-cell text={formatCurrency(o.gerealiseerd)} horizontal-alignment="right" />
      <nldd-text-cell>
        <nldd-container layout="row" gap="6" vertical-alignment="center">
          <Badge color={OPDRACHT_STATUS_COLORS[o.status as OpdrachtStatus] || 'coolgray'}>
            {OPDRACHT_STATUS_LABELS[o.status as OpdrachtStatus] || o.status}
          </Badge>
          <FccTrafficLights opdracht={o} />
        </nldd-container>
      </nldd-text-cell>
    </nldd-table-row>
  );
}

/** One opdracht card in the mobile list. */
function OpdrachtCard({ opdracht: o, onOpen }: { opdracht: Opdracht; onOpen: () => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', useCallback(() => onOpen(), [onOpen]));

  return (
    <nldd-card ref={ref} button accessible-label={o.titel}>
      <nldd-container padding="12" gap="8">
        <nldd-container layout="row" gap="8" vertical-alignment="top">
          <nldd-text size="sm" weight="medium">{o.titel}</nldd-text>
          <nldd-spacer direction="horizontal" size="flexible" />
          <Badge color={OPDRACHT_STATUS_COLORS[o.status as OpdrachtStatus] || 'coolgray'}>
            {OPDRACHT_STATUS_LABELS[o.status as OpdrachtStatus] || o.status}
          </Badge>
        </nldd-container>
        <nldd-container layout="wrap" gap="6" vertical-alignment="center">
          <Badge color={OPDRACHT_TYPE_COLORS[o.type as OpdrachtType] || 'coolgray'}>
            {OPDRACHT_TYPE_LABELS[o.type as OpdrachtType] || o.type}
          </Badge>
          <nldd-text size="xs" color="secondary">{o.begrotingsjaar}</nldd-text>
          {(o.opdrachtnemer?.afkorting || o.opdrachtnemer?.naam) && (
            <nldd-text size="xs" color="secondary">· {o.opdrachtnemer.afkorting || o.opdrachtnemer.naam}</nldd-text>
          )}
        </nldd-container>
        <nldd-container layout="row" gap="8">
          <nldd-text size="xs" color="secondary">Budget: {formatCurrency(o.budget)}</nldd-text>
          <nldd-spacer direction="horizontal" size="flexible" />
          <nldd-text size="xs" color="secondary">Gerealiseerd: {formatCurrency(o.gerealiseerd)}</nldd-text>
        </nldd-container>
      </nldd-container>
    </nldd-card>
  );
}

export function OpdrachtenPage() {
  const { openOpdrachtDetail } = useOpdrachtDetail();
  const { openOpdrachtCreate } = useOpdrachtCreate();
  const { currentPerson } = useCurrentPerson();
  const { hasPermission } = usePermissions();
  const [searchParams, setSearchParams] = useSearchParams();

  // API-level filters (sent to backend), seeded from URL params
  const [apiFilters, setApiFilters] = useState<OpdrachtFilters>(() => {
    const initial: OpdrachtFilters = {};
    const v = searchParams.get('verantwoordelijke_id');
    if (v) initial.verantwoordelijke_id = v;
    const i = searchParams.get('instrument_id');
    if (i) initial.instrument_id = i;
    return initial;
  });

  // Keep URL params in sync with apiFilters
  useEffect(() => {
    const params = new URLSearchParams();
    if (apiFilters.verantwoordelijke_id) params.set('verantwoordelijke_id', apiFilters.verantwoordelijke_id);
    if (apiFilters.instrument_id) params.set('instrument_id', apiFilters.instrument_id);
    setSearchParams(params, { replace: true });
  }, [apiFilters.verantwoordelijke_id, apiFilters.instrument_id, setSearchParams]);

  // Client-side filters
  const [searchInput, setSearchInput] = useState('');
  const searchQuery = useDebounce(searchInput, 200);
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set());

  const fccSync = useTriggerFccSync();
  const { data: fccSchema } = useFccSchema();
  const fccEnabled = Object.keys(fccSchema?.entity_sets ?? {}).length > 0;
  const { data: lastSync } = useLastFccSync();
  const bulkMatch = useMatchOpdrachtContactsBulk();
  const { data: opdrachten = [], isLoading } = useOpdrachten(apiFilters);
  const { data: summary } = useOpdrachtenSummary(apiFilters);
  const { data: alleEenheden = [] } = useOrganisatieFlat();
  // Externe organisaties zijn nu OrganisatieEenheid-rijen die niet behoren tot
  // de interne hiërarchie of synthetische groepen.
  const externeOrgs = useMemo(
    () =>
      alleEenheden.filter(
        (e) =>
          e.bron !== 'synthetisch' &&
          !['ministerie', 'directoraat_generaal', 'directie', 'afdeling', 'cluster', 'bureau', 'team'].includes(e.type),
      ),
    [alleEenheden],
  );
  const { data: people = [] } = usePeople();
  const { data: instrumenten = [] } = useNodes(NodeType.INSTRUMENT);

  // Derive year options from data
  const yearOptions: SelectOption[] = useMemo(() => {
    const years = [...new Set(opdrachten.map((o) => o.begrotingsjaar))].sort((a, b) => b - a);
    const currentYear = new Date().getFullYear();
    const allYears = years.length > 0 ? years : [currentYear - 1, currentYear, currentYear + 1];
    return allYears.map((y) => ({ value: String(y), label: String(y) }));
  }, [opdrachten]);

  // Derive opdrachtnemer options from externe organisaties
  const opdrachtnemerOptions: SelectOption[] = useMemo(
    () =>
      externeOrgs.map((o) => ({
        value: o.id,
        label: o.afkorting || o.naam,
      })),
    [externeOrgs],
  );

  // Verantwoordelijke options from people, with "Mijn opdrachten" at top
  const verantwoordelijkeOptions: SelectOption[] = useMemo(
    () => [
      ...(currentPerson
        ? [{ value: MY_OPDRACHTEN_SENTINEL, label: `Mijn opdrachten (${currentPerson.naam})` }]
        : []),
      ...people.map((p) => ({ value: p.id, label: p.naam })),
    ],
    [people, currentPerson],
  );

  // Instrument options from nodes
  const instrumentOptions: SelectOption[] = useMemo(
    () => instrumenten.map((n) => ({ value: n.id, label: n.title })),
    [instrumenten],
  );

  // Client-side filtering
  const filteredOpdrachten = useMemo(() => {
    let result = opdrachten;

    // Search filter
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (o) =>
          o.titel.toLowerCase().includes(q) ||
          o.opdrachtnemer?.naam?.toLowerCase().includes(q) ||
          o.opdrachtnemer?.afkorting?.toLowerCase().includes(q),
      );
    }

    // Type filter (client-side multi-select)
    if (typeFilter.size > 0) {
      result = result.filter((o) => typeFilter.has(o.type));
    }

    // Status filter (client-side multi-select)
    if (statusFilter.size > 0) {
      result = result.filter((o) => statusFilter.has(o.status));
    }

    return result;
  }, [opdrachten, searchQuery, typeFilter, statusFilter]);

  // Whether any search, dropdown or client-side filter is narrowing the set,
  // so the empty state can say "no matches" rather than "nothing here at all".
  const activeFilterCount = [
    typeFilter.size > 0,
    statusFilter.size > 0,
    !!apiFilters.begrotingsjaar,
    !!apiFilters.opdrachtnemer_eenheid_id,
    !!apiFilters.verantwoordelijke_id,
    !!apiFilters.instrument_id,
  ].filter(Boolean).length;
  const hasActiveFilter = !!searchQuery || activeFilterCount > 0;

  // Only matters below `sm`; from `sm` up the filters are always shown.
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Totals from server-side summary (for summary cards)
  const totaalBudget = summary?.totaal_budget ?? 0;
  const totaalGerealiseerd = summary?.totaal_gerealiseerd ?? 0;
  const uitnutting = summary?.uitnutting_percentage ?? 0;

  // Totals from filtered list (for table footer)
  const filteredBudget = filteredOpdrachten.reduce((sum, o) => sum + (o.budget ?? 0), 0);
  const filteredGerealiseerd = filteredOpdrachten.reduce(
    (sum, o) => sum + (o.gerealiseerd ?? 0),
    0,
  );

  return (
    <nldd-container gap="24">
      {/* Summary cards */}
      <nldd-collection layout="grid" item-min-width="160px" gap="12">
        <nldd-card>
          <nldd-container padding="16" gap="4">
            <nldd-text size="sm" color="secondary">Aantal opdrachten</nldd-text>
            <nldd-text size="lg" weight="bold">{summary?.count ?? opdrachten.length}</nldd-text>
          </nldd-container>
        </nldd-card>
        <nldd-card>
          <nldd-container padding="16" gap="4">
            <nldd-text size="sm" color="secondary">Totaal budget</nldd-text>
            <nldd-text size="lg" weight="bold">{formatCurrencyCompact(totaalBudget)}</nldd-text>
          </nldd-container>
        </nldd-card>
        <nldd-card>
          <nldd-container padding="16" gap="4">
            <nldd-text size="sm" color="secondary">Totaal gerealiseerd</nldd-text>
            <nldd-text size="lg" weight="bold">{formatCurrencyCompact(totaalGerealiseerd)}</nldd-text>
          </nldd-container>
        </nldd-card>
        <nldd-card>
          <nldd-container padding="16" gap="4">
            <nldd-text size="sm" color="secondary">Uitnutting</nldd-text>
            <nldd-text size="lg" weight="bold">{uitnutting.toFixed(1)}%</nldd-text>
          </nldd-container>
        </nldd-card>
      </nldd-collection>

      {/* Page header */}
      <nldd-toolbar accessible-label="Opdrachtacties">
        <nldd-toolbar-item slot="start" priority={1} min-width="224px">
          {/* A fixed width: a fit-content container measures its children and
              they measure it back. */}
          <nldd-container width="224px">
            <OpdrachtenSearchField value={searchInput} onChange={setSearchInput} />
          </nldd-container>
        </nldd-toolbar-item>
        {hasPermission('opdracht:update') && (
          <nldd-toolbar-item slot="end" priority={1}>
            <NlddButton
              variant="secondary"
              startIcon="sparkles"
              loading={bulkMatch.isPending}
              onClick={() => bulkMatch.mutate(true)}
              disabled={bulkMatch.isPending}
              text={bulkMatch.isPending ? 'Matchen...' : 'Contacten & eenheden matchen'}
              compactBelowSm
            />
            <nldd-menu-item slot="overflow" text="Contacten & eenheden matchen" icon="sparkles"></nldd-menu-item>
          </nldd-toolbar-item>
        )}
        {fccEnabled && hasPermission('fcc:sync') && (
          <nldd-toolbar-item slot="end" priority={2}>
            <NlddButton
              variant="secondary"
              startIcon="refresh"
              loading={fccSync.isPending}
              onClick={() => fccSync.mutate()}
              disabled={fccSync.isPending}
              text="FCC Sync"
              compactBelowSm
            />
            <nldd-menu-item slot="overflow" text="FCC Sync" icon="refresh"></nldd-menu-item>
          </nldd-toolbar-item>
        )}
        <nldd-toolbar-item slot="end" priority={4}>
          <NlddButton startIcon="plus" onClick={() => openOpdrachtCreate()} text="Nieuwe opdracht" compactBelowSm />
          <nldd-menu-item slot="overflow" text="Nieuwe opdracht" icon="plus"></nldd-menu-item>
        </nldd-toolbar-item>
      </nldd-toolbar>

      {/* Filters. From `sm` up they are always shown, as a grid of equal
          columns. On a phone they used to stack as six blocks of different
          widths and fill half the screen before the first opdracht; there
          they now fold away behind a toggle that counts the active ones.

          The show/hide is a plain div: a light-DOM utility class cannot
          reliably override a custom element's own display. */}
      <nldd-container gap="8">
        <div className="hidden-from-sm">
          <FiltersToggle activeCount={activeFilterCount} onChange={setFiltersOpen} />
        </div>
        <div id="opdrachten-filters" className={filtersOpen ? undefined : 'hidden-below-sm-block'}>
          <nldd-container
            layout="grid"
            gap="8"
            column-count={1}
            sm-column-count={2}
            md-column-count={3}
            lg-column-count={6}
          >
            <MultiSelect
              value={typeFilter}
              onChange={setTypeFilter}
              options={TYPE_OPTIONS}
              allLabel="Alle typen"
            />
            <MultiSelect
              value={statusFilter}
              onChange={setStatusFilter}
              options={STATUS_OPTIONS}
              allLabel="Alle statussen"
            />
            <CreatableSelect
              value={apiFilters.begrotingsjaar ? String(apiFilters.begrotingsjaar) : ''}
              onChange={(v) =>
                setApiFilters((f) => ({
                  ...f,
                  begrotingsjaar: v ? Number(v) : undefined,
                }))
              }
              options={yearOptions}
              placeholder="Alle jaren"
              searchable={false}
              onClear={() =>
                setApiFilters((f) => ({ ...f, begrotingsjaar: undefined }))
              }
            />
            <CreatableSelect
              value={apiFilters.opdrachtnemer_eenheid_id ?? ''}
              onChange={(v) =>
                setApiFilters((f) => ({
                  ...f,
                  opdrachtnemer_eenheid_id: v || undefined,
                }))
              }
              options={opdrachtnemerOptions}
              placeholder="Alle opdrachtnemers"
              onClear={() =>
                setApiFilters((f) => ({ ...f, opdrachtnemer_eenheid_id: undefined }))
              }
            />
            <CreatableSelect
              value={apiFilters.verantwoordelijke_id === currentPerson?.id ? MY_OPDRACHTEN_SENTINEL : (apiFilters.verantwoordelijke_id ?? '')}
              onChange={(v) => {
                const resolved = v === MY_OPDRACHTEN_SENTINEL ? currentPerson?.id : v;
                setApiFilters((f) => ({
                  ...f,
                  verantwoordelijke_id: resolved || undefined,
                }));
              }}
              options={verantwoordelijkeOptions}
              placeholder="Alle verantwoordelijken"
              onClear={() =>
                setApiFilters((f) => ({ ...f, verantwoordelijke_id: undefined }))
              }
            />
            <CreatableSelect
              value={apiFilters.instrument_id ?? ''}
              onChange={(v) =>
                setApiFilters((f) => ({
                  ...f,
                  instrument_id: v || undefined,
                }))
              }
              options={instrumentOptions}
              placeholder="Alle instrumenten"
              onClear={() =>
                setApiFilters((f) => ({ ...f, instrument_id: undefined }))
              }
            />
          </nldd-container>
        </div>
        {fccEnabled && lastSync?.last_synced_at && (
          <nldd-text size="xs" color="secondary">
            Laatste FCC-import: {timeAgo(lastSync.last_synced_at)}
          </nldd-text>
        )}
      </nldd-container>

      {/* Mobile card list. `nldd-table`'s own `sm-columns` collapses tracks
          rather than swapping to an entirely different card layout, so there
          is no single nldd component for "table on wide screens, cards on
          narrow ones". A custom element's own display can't reliably be
          overridden by a light-DOM utility class, so the visibility split
          itself stays a plain div; everything inside it is nldd. */}
      <div className="hidden-from-sm">
        <nldd-container gap="12">
          {isLoading ? (
            <nldd-inline-dialog variant="loading" text="Laden..." />
          ) : filteredOpdrachten.length === 0 ? (
            <nldd-inline-dialog
              text={hasActiveFilter ? 'Geen opdrachten gevonden' : 'Nog geen opdrachten'}
              supporting-text={
                hasActiveFilter
                  ? 'Pas je zoekopdracht of filters aan.'
                  : 'Zodra er een opdracht binnenkomt verschijnt die hier.'
              }
            />
          ) : (
            <>
              {filteredOpdrachten.map((o) => (
                <OpdrachtCard key={o.id} opdracht={o} onOpen={() => openOpdrachtDetail(o.id)} />
              ))}
              <nldd-card>
                <nldd-container padding="16" layout="row" gap="8">
                  <nldd-text size="sm" weight="medium">Totaal ({filteredOpdrachten.length})</nldd-text>
                  <nldd-spacer direction="horizontal" size="flexible" />
                  <nldd-text size="sm" weight="medium">{formatCurrency(filteredBudget)}</nldd-text>
                  <nldd-text size="sm" weight="medium">{formatCurrency(filteredGerealiseerd)}</nldd-text>
                </nldd-container>
              </nldd-card>
            </>
          )}
        </nldd-container>
      </div>

      {/* Desktop table */}
      <div className="visible-from-sm">
        <nldd-container gap="8">
        <nldd-table
          columns="minmax(200px,1.6fr) 140px 80px minmax(140px,1fr) minmax(140px,1fr) 120px 120px minmax(140px,1fr)"
          accessible-label="Opdrachten"
        >
          <nldd-table-row slot="header">
            <nldd-text-cell text="Titel" />
            <nldd-text-cell text="Type" />
            <nldd-text-cell text="Jaar" />
            <nldd-text-cell text="Opdrachtnemer" />
            <nldd-text-cell text="Instrument" />
            <nldd-text-cell text="Budget" horizontal-alignment="right" />
            <nldd-text-cell text="Gerealiseerd" horizontal-alignment="right" />
            <nldd-text-cell text="Status" />
          </nldd-table-row>
          {isLoading ? (
            <div slot="empty">
              <nldd-inline-dialog variant="loading" text="Laden..." />
            </div>
          ) : filteredOpdrachten.length === 0 ? (
            <div slot="empty">
              <nldd-inline-dialog
                text={hasActiveFilter ? 'Geen opdrachten gevonden' : 'Nog geen opdrachten'}
                supporting-text={
                  hasActiveFilter
                    ? 'Pas je zoekopdracht of filters aan.'
                    : 'Zodra er een opdracht binnenkomt verschijnt die hier.'
                }
              />
            </div>
          ) : (
            filteredOpdrachten.map((o) => (
              <OpdrachtRow key={o.id} opdracht={o} onOpen={() => openOpdrachtDetail(o.id)} />
            ))
          )}
        </nldd-table>
          {filteredOpdrachten.length > 0 && (
            <nldd-container layout="row" gap="24" padding-inline="8" padding-block="8">
              <nldd-text size="sm" weight="medium">Totaal ({filteredOpdrachten.length} opdrachten)</nldd-text>
              <nldd-spacer direction="horizontal" size="flexible" />
              <nldd-text size="sm" weight="medium">{formatCurrency(filteredBudget)}</nldd-text>
              <nldd-text size="sm" weight="medium">{formatCurrency(filteredGerealiseerd)}</nldd-text>
            </nldd-container>
          )}
        </nldd-container>
      </div>
    </nldd-container>
  );
}
