import { useCallback, useRef, useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Card } from '@/components/common/Card';
import { Select } from '@/components/common/Select';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { EmptyState } from '@/components/common/EmptyState';
import { OrganisatieTree } from '@/components/organisatie/OrganisatieTree';
import { OrganisatieDetail } from '@/components/organisatie/OrganisatieDetail';
import { OrganisatieForm } from '@/components/organisatie/OrganisatieForm';
import { PersonEditForm } from '@/components/people/PersonEditForm';
import { Icon } from '@/components/nldd/Icon';
import { eventValue, orUndef, useNlddEvent } from '@/components/nldd/events';
import {
  useOrganisatieTree,
  useCreateOrganisatieEenheid,
  useUpdateOrganisatieEenheid,
  useDeleteOrganisatieEenheid,
} from '@/hooks/useOrganisatie';
import { useAddPersonOrganisatie, usePersonOrganisaties } from '@/hooks/usePeople';
import { usePersonFormSubmit } from '@/hooks/usePersonFormSubmit';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { todayISO } from '@/utils/dates';
import type { OrganisatieEenheid, OrganisatieEenheidCreate, OrganisatieEenheidUpdate, Person } from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

/** Reads `checked` off an nldd-checkbox-field's `change` detail. */
function checkedValue(event: Event): boolean {
  return Boolean((event as CustomEvent<{ checked?: boolean }>).detail?.checked);
}

function HistorischCheckbox({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', useCallback((e: Event) => onChange(checkedValue(e)), [onChange]));
  return <nldd-checkbox-field ref={ref} label="Historisch" checked={orUndef(checked)} />;
}

/** The organisatie tree search field: `nldd-search-field` with its `input` event bridged to React. */
function OrganisatieSearchField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));
  return (
    <nldd-search-field
      ref={ref}
      value={value}
      placeholder="Zoek organisatie of afkorting..."
      accessible-label="Zoek organisatie of afkorting"
    />
  );
}

export function OrganisatiePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get('eenheid'));
  const [showForm, setShowForm] = useState(false);
  const [editData, setEditData] = useState<OrganisatieEenheid | null>(null);
  const [defaultParentId, setDefaultParentId] = useState<string | null>(null);

  // Person form state
  const [showPersonForm, setShowPersonForm] = useState(false);
  const [editPerson, setEditPerson] = useState<Person | null>(null);
  const [createdApiKey, setCreatedApiKey] = useState<string | null>(null);

  // Boom-zoek + filters
  const [searchTerm, setSearchTerm] = useState('');
  const [includeHistorisch, setIncludeHistorisch] = useState(false);
  const [bronFilter, setBronFilter] = useState<'alle' | 'handmatig' | 'tooi' | 'scrape'>('alle');

  // Sync ?eenheid= param on arrival, then clear it
  useEffect(() => {
    const eenheidParam = searchParams.get('eenheid');
    if (eenheidParam) {
      setSelectedId(eenheidParam);
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const { data: tree = [], isLoading } = useOrganisatieTree(includeHistorisch);
  const { currentPerson } = useCurrentPerson();
  const { data: ownPlacements = [] } = usePersonOrganisaties(
    currentPerson?.id ?? null,
  );

  // Default-open: pad van root naar elk eigen-organisatie-id van de gebruiker.
  // Met 1900+ nodes is alles dicht onhanteerbaar; je eigen ministerie hoort
  // wel als entrypoint open te staan. We pakken alle actieve placements
  // (functietitel-rollen onder een eenheid) van currentPerson.
  const expandedByDefaultIds = useMemo(() => {
    const eigenIds = new Set(ownPlacements.map((p) => p.organisatie_eenheid_id));
    if (eigenIds.size === 0) return new Set<string>();
    const open = new Set<string>();
    const walk = (nodes: typeof tree, ancestors: string[]): boolean => {
      let touched = false;
      for (const n of nodes) {
        const path = [...ancestors, n.id];
        const hitChild = walk(n.children, path);
        if (eigenIds.has(n.id) || hitChild) {
          // Open alle ancestors plus de matchende node zelf, zodat children
          // van de eigen-org zichtbaar worden zonder dat de eigen-org per
          // se hoeft te worden geklikt.
          for (const aid of path) open.add(aid);
          touched = true;
        }
      }
      return touched;
    };
    walk(tree, []);
    return open;
  }, [tree, ownPlacements]);

  // Filter de boom op zoekterm + bron: een node blijft staan als hijzelf
  // matcht OF een afstammeling matcht. Synthetische groepen worden altijd
  // getoond als ze matchende children hebben (anders wordt de tree-structuur
  // onnavigeerbaar).
  const filteredTree = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    const matchesBron = (bron: string | null | undefined): boolean => {
      if (bronFilter === 'alle') return true;
      if (bronFilter === 'scrape')
        return bron === 'organogram_scrape' || bron === 'fcc_import';
      if (bronFilter === 'tooi') return bron === 'tooi';
      return bron === 'handmatig';
    };
    const matches = (n: (typeof tree)[number]): boolean => {
      // Synthetische groepen: tonen als ze matchende children hebben
      if (n.bron === 'synthetisch') return n.children.some(matches);
      const termMatch =
        !term ||
        n.naam.toLowerCase().includes(term) ||
        (n.afkorting?.toLowerCase().includes(term) ?? false);
      const bronMatch = matchesBron(n.bron);
      const self = termMatch && bronMatch;
      const child = n.children.some(matches);
      return self || child;
    };
    const filter = (nodes: typeof tree): typeof tree =>
      nodes
        .filter(matches)
        .map((n) => ({ ...n, children: filter(n.children) }));
    return filter(tree);
  }, [tree, searchTerm, bronFilter]);
  const createMutation = useCreateOrganisatieEenheid();
  const updateMutation = useUpdateOrganisatieEenheid();
  const deleteMutation = useDeleteOrganisatieEenheid();
  const addPlacementMutation = useAddPersonOrganisatie();
  const { handleSubmit: handlePersonFormSubmit, isPending: isPersonPending } = usePersonFormSubmit(
    () => {
      setShowPersonForm(false);
      setCreatedApiKey(null);
    },
    (person) => {
      if (person.api_key && person.is_agent) {
        setCreatedApiKey(person.api_key);
        setEditPerson(person);
      }
    },
  );

  const handleAdd = (parentId: string | null) => {
    setEditData(null);
    setDefaultParentId(parentId);
    setShowForm(true);
  };

  const handleEdit = () => {
    if (!selectedId) return;
    // Find the selected node in the flat tree
    const findNode = (nodes: typeof tree): OrganisatieEenheid | null => {
      for (const n of nodes) {
        if (n.id === selectedId) return n;
        const found = findNode(n.children);
        if (found) return found;
      }
      return null;
    };
    const node = findNode(tree);
    if (node) {
      setEditData(node);
      setDefaultParentId(null);
      setShowForm(true);
    }
  };

  const handleDelete = () => {
    if (!selectedId) return;
    deleteMutation.mutate(selectedId, {
      onSuccess: () => setSelectedId(null),
    });
  };

  const handleFormSubmit = (data: OrganisatieEenheidCreate | OrganisatieEenheidUpdate) => {
    if (editData) {
      updateMutation.mutate(
        { id: editData.id, data: data as OrganisatieEenheidUpdate },
        { onSuccess: () => setShowForm(false) },
      );
    } else {
      createMutation.mutate(data as OrganisatieEenheidCreate, {
        onSuccess: () => setShowForm(false),
      });
    }
  };

  // Person handlers
  const [defaultIsAgent, setDefaultIsAgent] = useState(false);

  const handleAddPerson = () => {
    setEditPerson(null);
    setDefaultIsAgent(false);
    setShowPersonForm(true);
  };

  const handleAddAgent = () => {
    setEditPerson(null);
    setDefaultIsAgent(true);
    setShowPersonForm(true);
  };

  const handleEditPerson = (person: Person) => {
    setEditPerson(person);
    setShowPersonForm(true);
  };

  const handleDragStartPerson = (e: React.DragEvent, person: Person) => {
    e.dataTransfer.setData('application/person-id', person.id);
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleDropPerson = (personId: string, targetNodeId: string) => {
    addPlacementMutation.mutate({
      personId,
      data: {
        organisatie_eenheid_id: targetNodeId,
        dienstverband: 'in_dienst',
        start_datum: todayISO(),
      },
    });
  };

  if (isLoading) {
    return <LoadingSpinner padding="48" />;
  }

  const isEmpty = tree.length === 0;

  return (
    <nldd-container gap="24">
      {/* Page header */}
      <nldd-toolbar accessible-label="Organisatieacties">
        <nldd-toolbar-item slot="start" priority={1}>
          <nldd-text size="sm" color="secondary">
            Beheer de organisatiestructuur: Ministerie, DG, Directie, Afdeling, Team.
          </nldd-text>
        </nldd-toolbar-item>
        <nldd-toolbar-item slot="end">
          <NlddButton startIcon="plus" onClick={() => handleAdd(null)} text="Eenheid toevoegen" />
          <nldd-menu-item slot="overflow" text="Eenheid toevoegen" icon="plus" />
        </nldd-toolbar-item>
      </nldd-toolbar>

      {isEmpty ? (
        <EmptyState
          icon="apartment-building"
          title="Nog geen organisatie-eenheden"
          description="Begin met het opzetten van de organisatiestructuur door een top-niveau eenheid toe te voegen."
          action={
            <NlddButton variant="primary" onClick={() => handleAdd(null)} text="Eerste eenheid aanmaken" />
          }
        />
      ) : (
        <nldd-container layout="grid" column-count={1} lg-column-count={3} gap="24">
          {/* Left panel: Tree */}
          <Card>
            <nldd-container gap="8" padding="8">
              <OrganisatieSearchField value={searchTerm} onChange={setSearchTerm} />
              <nldd-container layout="row" width="full" gap="8" horizontal-alignment="right" vertical-alignment="center" padding-inline="4">
                <HistorischCheckbox checked={includeHistorisch} onChange={setIncludeHistorisch} />
                <nldd-container width="160px">
                  <Select
                    value={bronFilter}
                    onChange={(e) => setBronFilter(e.target.value as typeof bronFilter)}
                    // `title` is a tooltip, not a name: a screen reader
                    // announces the select as unlabelled and reads only the
                    // selected option, so "Alleen TOOI" arrives without
                    // anything saying what it filters.
                    aria-label="Filter op bron"
                    options={[
                      { value: 'alle', label: 'Alle bronnen' },
                      { value: 'handmatig', label: 'Alleen handmatig' },
                      { value: 'tooi', label: 'Alleen TOOI' },
                      { value: 'scrape', label: 'Alleen scrape/import' },
                    ]}
                  />
                </nldd-container>
              </nldd-container>
              <OrganisatieTree
                tree={filteredTree}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onAdd={handleAdd}
                onDropPerson={handleDropPerson}
                searchTerm={searchTerm}
                expandedByDefaultIds={expandedByDefaultIds}
              />
            </nldd-container>
          </Card>

          {/* Right panel: Detail — spans the remaining two columns at lg */}
          <div style={{ gridColumn: 'span 2' }}>
            {selectedId ? (
              <Card>
                <nldd-container padding="8">
                  <OrganisatieDetail
                    selectedId={selectedId}
                    onEdit={handleEdit}
                    onDelete={handleDelete}
                    onAddChild={() => handleAdd(selectedId)}
                    onAddPerson={handleAddPerson}
                    onAddAgent={handleAddAgent}
                    onEditPerson={handleEditPerson}
                    onDragStartPerson={handleDragStartPerson}
                    onDropPerson={handleDropPerson}
                  />
                </nldd-container>
              </Card>
            ) : (
              <Card>
                <nldd-container gap="12" padding="48" horizontal-alignment="center">
                  <Icon name="apartment-building" size="32" style={{ opacity: 0.3 }} aria-hidden="true" />
                  <nldd-text size="sm" color="secondary" horizontal-alignment="center">
                    Selecteer een eenheid in de boomstructuur.
                  </nldd-text>
                </nldd-container>
              </Card>
            )}
          </div>
        </nldd-container>
      )}

      {/* Create/Edit org form */}
      <OrganisatieForm
        open={showForm}
        onClose={() => setShowForm(false)}
        onSubmit={handleFormSubmit}
        isLoading={createMutation.isPending || updateMutation.isPending}
        editData={editData}
        defaultParentId={defaultParentId}
      />

      {/* Create/Edit person form */}
      <PersonEditForm
        open={showPersonForm}
        onClose={() => {
          setShowPersonForm(false);
          setCreatedApiKey(null);
        }}
        onSubmit={handlePersonFormSubmit}
        isLoading={isPersonPending}
        editData={editPerson}
        defaultIsAgent={defaultIsAgent}
        defaultOrgEenheidId={selectedId || undefined}
        createdApiKey={createdApiKey}
      />
    </nldd-container>
  );
}
