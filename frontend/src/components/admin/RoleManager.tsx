import { useRef, useState, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { usePeople, useMergePersons } from '@/hooks/usePeople';
import { useAuth } from '@/contexts/AuthContext';
import { usePermissions } from '@/hooks/usePermissions';
import { isPersonOnline, formatRelativeTime } from '@/utils/people';
import { formatFunctie } from '@/types';
import { useOrganisatieFlat } from '@/hooks/useOrganisatie';
import {
  useRoles,
  usePersonRoleAssignments,
  useAssignRole,
  useRevokeRole,
} from '@/hooks/useRoles';
import type { PersonRoleAssignment } from '@/hooks/useRoles';
import {
  usePersonResourcePermissions,
  useRemovePersonResourcePermission,
} from '@/hooks/useResourcePermissions';
import type { PersonResourcePermission } from '@/hooks/useResourcePermissions';
import { useMutationWithError } from '@/hooks/useMutationWithError';
import { apiGet, apiPost } from '@/api/client';
import { queryKeys } from '@/hooks/queryKeys';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Select } from '@/components/common/Select';

function AssignmentRow({
  assignment,
  onRevoke,
  revoking,
  canRevoke,
}: {
  assignment: PersonRoleAssignment;
  onRevoke: (id: string) => void;
  revoking: boolean;
  canRevoke: boolean;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <nldd-table-row>
      <nldd-text-cell text={assignment.role_naam || assignment.role_id} size="sm" />
      <nldd-text-cell
        text={assignment.organisatie_eenheid_naam || '-'}
        color="secondary"
        size="sm"
        hide-below="md"
      />
      <nldd-text-cell
        text={new Date(assignment.start_datum).toLocaleDateString('nl-NL')}
        color="secondary"
        size="sm"
        hide-below="lg"
      />
      <nldd-text-cell
        text={assignment.eind_datum ? new Date(assignment.eind_datum).toLocaleDateString('nl-NL') : '-'}
        color="secondary"
        size="sm"
        hide-below="lg"
      />
      <nldd-text-cell>
        {!canRevoke ? null : confirmDelete ? (
          <nldd-container layout="row" gap="4" vertical-alignment="center">
            <NlddButton
              text="Ja"
              variant="destructive"
              size="xs"
              disabled={revoking}
              onClick={() => {
                onRevoke(assignment.id);
                setConfirmDelete(false);
              }}
            />
            <NlddButton
              text="Nee"
              variant="neutral-tinted"
              size="xs"
              onClick={() => setConfirmDelete(false)}
            />
          </nldd-container>
        ) : (
          <NlddIconButton
            icon="trash"
            accessibleLabel="Intrekken"
            variant="neutral-transparent"
            size="sm"
            onClick={() => setConfirmDelete(true)}
          />
        )}
      </nldd-text-cell>
    </nldd-table-row>
  );
}

function PersonRolesPanel({
  personId,
}: {
  personId: string;
}) {
  const { person: authPerson } = useAuth();
  const { isSuperAdmin, hasSystemPermission, managesEenheid } = usePermissions();
  const isSelf = authPerson?.id === personId;
  const { data: assignments, isLoading } = usePersonRoleAssignments(personId);
  const { data: roles } = useRoles();
  const { data: orgUnits } = useOrganisatieFlat();
  const assignRole = useAssignRole();
  const revokeRole = useRevokeRole();

  const [showForm, setShowForm] = useState(false);
  const [selectedRoleId, setSelectedRoleId] = useState('');
  const [selectedOrgId, setSelectedOrgId] = useState('');
  const [startDatum, setStartDatum] = useState('');
  const [eindDatum, setEindDatum] = useState('');

  const startDatumRef = useRef<HTMLElement>(null);
  const eindDatumRef = useRef<HTMLElement>(null);
  useNlddEvent(startDatumRef, 'input', (e) => setStartDatum(eventValue(e)));
  useNlddEvent(eindDatumRef, 'input', (e) => setEindDatum(eventValue(e)));

  const selectedRole = roles?.find((r) => r.id === selectedRoleId);
  const isSystemLevel = selectedRole?.level === 'system';

  // Determine the caller's max role rank for filtering
  const myMaxRank = useMemo(() => {
    if (isSuperAdmin) return 999;
    const myRoleIds = authPerson?.roles?.map((r) => r.role_id) ?? [];
    return Math.max(0, ...(roles ?? []).filter((r) => myRoleIds.includes(r.id)).map((r) => r.rank));
  }, [isSuperAdmin, authPerson?.roles, roles]);

  // Offer only eenheden where the backend will accept the assignment: the
  // ones this person manages (and everything below), or all of them for a
  // system-wide role.
  const scopedOrgUnits = useMemo(() => {
    if (!orgUnits) return [];
    if (hasSystemPermission('people:assign_role')) return orgUnits;
    return orgUnits.filter((u) => managesEenheid(u.id));
  }, [orgUnits, hasSystemPermission, managesEenheid]);

  // Filter roles to those the user can assign (rank < myMaxRank)
  const assignableRoles = useMemo(() => {
    if (!roles) return [];
    if (isSuperAdmin) return roles;
    // System roles are super_admin-only; the backend refuses them otherwise.
    return roles.filter((r) => r.level !== 'system' && r.rank < myMaxRank);
  }, [roles, myMaxRank, isSuperAdmin]);

  const handleAssign = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedRoleId) return;

    assignRole.mutate(
      {
        person_id: personId,
        role_id: selectedRoleId,
        organisatie_eenheid_id:
          isSystemLevel ? undefined : selectedOrgId || undefined,
        start_datum: startDatum || undefined,
        eind_datum: eindDatum || undefined,
      },
      {
        onSuccess: () => {
          setSelectedRoleId('');
          setSelectedOrgId('');
          setStartDatum('');
          setEindDatum('');
          setShowForm(false);
        },
      },
    );
  };

  const handleRevoke = (assignmentId: string) => {
    revokeRole.mutate(assignmentId);
  };

  if (isLoading) {
    return (
      <nldd-box>
        <nldd-container padding="12">
          <nldd-activity-indicator size="16" />
        </nldd-container>
      </nldd-box>
    );
  }

  return (
    <nldd-box>
      <nldd-container padding="12" gap="4">
        <nldd-title size={6}><h3>Rollen</h3></nldd-title>
      {/* Current assignments table */}
      {assignments && assignments.length > 0 ? (
        <nldd-table
          columns="minmax(120px,1fr) 140px 100px 100px 48px"
          sm-columns="1fr 48px"
          md-columns="1fr 140px 48px"
          accessible-label="Roltoewijzingen"
          background="tinted"
        >
          <nldd-table-row slot="header">
            <nldd-text-cell text="Rol" size="sm" />
            <nldd-text-cell text="Eenheid" size="sm" hide-below="md" />
            <nldd-text-cell text="Vanaf" size="sm" hide-below="lg" />
            <nldd-text-cell text="Tot" size="sm" hide-below="lg" />
            <nldd-text-cell />
          </nldd-table-row>
          {assignments.map((a) => {
            const roleRank = roles?.find((r) => r.id === a.role_id)?.rank ?? 0;
            // Stepping down from your own role is always allowed, except
            // super_admin; anyone else's role needs a higher rank.
            const canRevoke = isSelf
              ? a.role_id !== 'super_admin'
              : isSuperAdmin || roleRank < myMaxRank;
            return (
              <AssignmentRow
                key={a.id}
                assignment={a}
                onRevoke={handleRevoke}
                revoking={revokeRole.isPending}
                canRevoke={canRevoke}
              />
            );
          })}
        </nldd-table>
      ) : (
        <nldd-text size="sm" color="secondary">Geen rollen.</nldd-text>
      )}

      {/* Add role button / form — directly after roles. Nobody but a
          super_admin assigns roles to themselves. */}
      {isSelf && !isSuperAdmin ? null : !showForm ? (
        <NlddButton
          text="Rol toewijzen"
          startIcon="plus"
          variant="neutral-transparent"
          size="sm"
          onClick={() => setShowForm(true)}
        />
      ) : (
        <nldd-form>
        <form onSubmit={handleAssign}>
          <nldd-container gap="12">
          <nldd-container layout="grid" column-count={2} gap="12">
            {/* Role selector */}
            <Select
              size="sm"
              label="Rol"
              value={selectedRoleId}
              onChange={(e) => {
                const next = e.target.value;
                setSelectedRoleId(next);
                // Reset org when switching to system role
                const role = roles?.find((r) => r.id === next);
                if (role?.level === 'system') setSelectedOrgId('');
              }}
              placeholder="Kies een rol..."
              options={assignableRoles.map((role) => ({
                value: role.id,
                label: role.description ? `${role.naam} - ${role.description}` : role.naam,
              }))}
              required
            />

            {/* Org unit selector (hidden for system roles) */}
            {!isSystemLevel && (
              <Select
                size="sm"
                label="Organisatie-eenheid"
                value={selectedOrgId}
                onChange={(e) => setSelectedOrgId(e.target.value)}
                placeholder="Kies een eenheid..."
                options={scopedOrgUnits.map((unit) => ({ value: unit.id, label: unit.naam }))}
                required={!!selectedRoleId}
              />
            )}

            {/* Start date */}
            <nldd-form-field label="Startdatum" optional>
              <nldd-date-field ref={startDatumRef} value={startDatum} size="sm" />
            </nldd-form-field>

            {/* End date */}
            <nldd-form-field label="Einddatum" optional>
              <nldd-date-field ref={eindDatumRef} value={eindDatum} size="sm" />
            </nldd-form-field>
          </nldd-container>

          <nldd-container layout="row" gap="8">
            <NlddButton
              type="submit"
              text="Toewijzen"
              startIcon="plus"
              size="sm"
              disabled={assignRole.isPending || !selectedRoleId}
            />
            <NlddButton
              type="button"
              text="Annuleren"
              variant="neutral-tinted"
              size="sm"
              onClick={() => {
                setShowForm(false);
                setSelectedRoleId('');
                setSelectedOrgId('');
                setStartDatum('');
                setEindDatum('');
              }}
            />
          </nldd-container>
          </nldd-container>
        </form>
        </nldd-form>
      )}

      {/* Resource permissions */}
      <PersonResourcePermissionsSection personId={personId} />
      </nldd-container>
    </nldd-box>
  );
}

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  corpus_node: 'Beleidsobject',
  initiatief: 'Initiatief',
  lead: 'Lead',
  team: 'Team',
  opdracht: 'Opdracht',
};

function ResourcePermissionRow({
  rp,
  onRemove,
  removing,
}: {
  rp: PersonResourcePermission;
  onRemove: (id: string) => void;
  removing: boolean;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <nldd-table-row>
      <nldd-text-cell text={rp.resource_name} size="sm" />
      <nldd-text-cell
        text={RESOURCE_TYPE_LABELS[rp.resource_type] || rp.resource_type}
        color="secondary"
        size="sm"
        hide-below="md"
      />
      <nldd-text-cell text={rp.rol} color="secondary" size="sm" />
      <nldd-text-cell>
        {confirmDelete ? (
          <nldd-container layout="row" gap="4" vertical-alignment="center">
            <NlddButton
              text="Ja"
              variant="destructive"
              size="xs"
              disabled={removing}
              onClick={() => {
                onRemove(rp.id);
                setConfirmDelete(false);
              }}
            />
            <NlddButton
              text="Nee"
              variant="neutral-tinted"
              size="xs"
              onClick={() => setConfirmDelete(false)}
            />
          </nldd-container>
        ) : (
          <NlddIconButton
            icon="trash"
            accessibleLabel="Verwijderen"
            variant="neutral-transparent"
            size="sm"
            onClick={() => setConfirmDelete(true)}
          />
        )}
      </nldd-text-cell>
    </nldd-table-row>
  );
}

const RESOURCE_ROLE_OPTIONS = [
  { value: 'eigenaar', label: 'Eigenaar' },
  { value: 'betrokken', label: 'Betrokken' },
  { value: 'adviseur', label: 'Adviseur' },
  { value: 'contributor', label: 'Contributor' },
];

const RESOURCE_TYPE_OPTIONS = [
  { value: 'corpus_node', label: 'Beleidsobject' },
  { value: 'initiatief', label: 'Initiatief' },
  { value: 'lead', label: 'Lead' },
  { value: 'opdracht', label: 'Opdracht' },
];

interface ResourceOption {
  id: string;
  label: string;
}

const RESOURCE_API_MAP: Record<string, { url: string; map: (item: Record<string, unknown>) => ResourceOption }> = {
  corpus_node: { url: '/api/nodes', map: (n) => ({ id: n.id as string, label: n.title as string }) },
  initiatief: { url: '/api/initiatieven', map: (i) => ({ id: i.id as string, label: i.naam as string }) },
  lead: { url: '/api/leads', map: (l) => ({ id: l.id as string, label: l.title as string }) },
  opdracht: { url: '/api/opdrachten', map: (o) => ({ id: o.id as string, label: o.titel as string }) },
};

function useResourceOptions(resourceType: string) {
  const config = RESOURCE_API_MAP[resourceType];
  const { data } = useQuery({
    queryKey: ['resource-options', resourceType],
    queryFn: () => apiGet<Record<string, unknown>[]>(config.url),
    enabled: !!config,
    staleTime: 60_000,
  });

  return useMemo(
    () => (data ?? []).map(config?.map ?? (() => ({ id: '', label: '' }))),
    [data, config],
  );
}

function PersonResourcePermissionsSection({ personId }: { personId: string }) {
  const { hasPermission } = usePermissions();
  const canManageRp = hasPermission('resource_permission:manage');
  const { data: perms } = usePersonResourcePermissions(personId);
  const removeRp = useRemovePersonResourcePermission(personId);
  const queryClient = useQueryClient();

  const [showForm, setShowForm] = useState(false);
  const [selectedResourceType, setSelectedResourceType] = useState('');
  const [selectedResourceId, setSelectedResourceId] = useState('');
  const [selectedRol, setSelectedRol] = useState('');

  const resourceOptions = useResourceOptions(selectedResourceType);

  const addPermission = useMutationWithError({
    mutationFn: (data: {
      resourceType: string;
      resourceId: string;
      person_id: string;
      rol: string;
    }) =>
      apiPost(
        `/api/resource-permissions/${data.resourceType}/${data.resourceId}`,
        { person_id: data.person_id, rol: data.rol },
      ),
    errorMessage: 'Fout bij toevoegen resource permissie',
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.admin.personResourcePermissions(personId),
      });
    },
  });

  const resetForm = () => {
    setSelectedResourceType('');
    setSelectedResourceId('');
    setSelectedRol('');
    setShowForm(false);
  };

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedResourceType || !selectedResourceId || !selectedRol) return;

    addPermission.mutate(
      {
        resourceType: selectedResourceType,
        resourceId: selectedResourceId,
        person_id: personId,
        rol: selectedRol,
      },
      { onSuccess: resetForm },
    );
  };

  const hasPerms = perms && perms.length > 0;

  return (
    <nldd-container gap="12">
      <nldd-divider />
      <nldd-title size={6}><h3>Resource permissies</h3></nldd-title>
      {hasPerms && (
        <nldd-table
          columns="minmax(120px,1fr) 140px 100px 48px"
          sm-columns="1fr 48px"
          md-columns="1fr 100px 48px"
          accessible-label="Resource permissies"
          background="tinted"
        >
          <nldd-table-row slot="header">
            <nldd-text-cell text="Naam" size="sm" />
            <nldd-text-cell text="Type" size="sm" hide-below="lg" />
            <nldd-text-cell text="Rol" size="sm" hide-below="md" />
            <nldd-text-cell />
          </nldd-table-row>
          {perms.map((rp) => (
            <ResourcePermissionRow
              key={rp.id}
              rp={rp}
              onRemove={(id) => removeRp.mutate(id)}
              removing={removeRp.isPending}
            />
          ))}
        </nldd-table>
      )}
      {!hasPerms && !showForm && (
        <nldd-text size="sm" color="secondary">Geen resource permissies.</nldd-text>
      )}

      {!canManageRp ? null : !showForm ? (
        <NlddButton
          text="Resource permissie toevoegen"
          startIcon="plus"
          variant="neutral-transparent"
          size="sm"
          onClick={() => setShowForm(true)}
        />
      ) : (
        <nldd-form>
        <form onSubmit={handleAdd}>
          <nldd-container gap="12">
          <nldd-container layout="grid" column-count={3} gap="12">
            <Select
              size="sm"
              label="Resource type"
              value={selectedResourceType}
              onChange={(e) => {
                setSelectedResourceType(e.target.value);
                setSelectedResourceId('');
              }}
              placeholder="Kies type..."
              options={RESOURCE_TYPE_OPTIONS}
              required
            />

            <Select
              size="sm"
              label="Resource"
              value={selectedResourceId}
              onChange={(e) => setSelectedResourceId(e.target.value)}
              placeholder={selectedResourceType ? 'Kies resource...' : 'Kies eerst type'}
              options={resourceOptions.map((opt) => ({ value: opt.id, label: opt.label }))}
              required
              disabled={!selectedResourceType}
            />

            <Select
              size="sm"
              label="Rol"
              value={selectedRol}
              onChange={(e) => setSelectedRol(e.target.value)}
              placeholder="Kies rol..."
              options={RESOURCE_ROLE_OPTIONS}
              required
            />
          </nldd-container>

          <nldd-container layout="row" gap="8">
            <NlddButton
              type="submit"
              text="Toevoegen"
              startIcon="plus"
              size="sm"
              disabled={
                addPermission.isPending ||
                !selectedResourceType ||
                !selectedResourceId ||
                !selectedRol
              }
            />
            <NlddButton
              type="button"
              text="Annuleren"
              variant="neutral-tinted"
              size="sm"
              onClick={resetForm}
            />
          </nldd-container>
          </nldd-container>
        </form>
        </nldd-form>
      )}
    </nldd-container>
  );
}

export function RoleManager() {
  const { person: authPerson } = useAuth();
  const { isSuperAdmin } = usePermissions();
  const { data: people, isLoading: loadingPeople } = usePeople();
  const { data: roles, isLoading: loadingRoles } = useRoles();
  const [expandedPersonId, setExpandedPersonId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [mergeTargetId, setMergeTargetId] = useState<string | null>(null);
  const [showMergeConfirm, setShowMergeConfirm] = useState(false);
  const merge = useMergePersons();
  const searchRef = useRef<HTMLElement>(null);
  const mergeTargetGroupRef = useRef<HTMLElement>(null);

  useNlddEvent(searchRef, 'input', (e) => setSearchQuery(eventValue(e)));

  const filteredPeople = useMemo(() => {
    if (!people) return [];
    const q = searchQuery.toLowerCase().trim();
    if (!q) return people;
    return people.filter(
      (p) =>
        p.naam.toLowerCase().includes(q) ||
        (p.email && p.email.toLowerCase().includes(q)) ||
        (p.functie && p.functie.toLowerCase().includes(q)),
    );
  }, [people, searchQuery]);

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        if (mergeTargetId === id) setMergeTargetId(null);
      } else {
        next.add(id);
        if (!mergeTargetId) setMergeTargetId(id);
      }
      return next;
    });
  };

  const selectedPeople = useMemo(
    () => (people ?? []).filter((p) => selectedIds.has(p.id)),
    [people, selectedIds],
  );

  useNlddEvent(mergeTargetGroupRef, 'change', (e) => {
    const id = eventValue(e);
    if (id) setMergeTargetId(id);
  });

  const handleMerge = async () => {
    if (!mergeTargetId || selectedIds.size < 2) return;
    const sourceIds = [...selectedIds].filter((id) => id !== mergeTargetId);
    await merge.mutateAsync({ sourceIds, targetId: mergeTargetId });
    setSelectedIds(new Set());
    setMergeTargetId(null);
    setShowMergeConfirm(false);
  };

  if (loadingPeople || loadingRoles) {
    return <LoadingSpinner padding="32" />;
  }

  return (
    <nldd-container gap="16">
      {/* Description */}
      <nldd-container layout="row" gap="8">
        <nldd-icon icon="shield" size="16" color="accent" />
        <nldd-text size="sm" color="secondary">
          Beheer roltoewijzingen per persoon. Klik op een persoon om rollen te bekijken, toe te
          wijzen of in te trekken.
          {roles && roles.length > 0 && (
            <> Beschikbare rollen: {roles.map((r) => r.naam).join(', ')}.</>
          )}
        </nldd-text>
      </nldd-container>

      {/* Search */}
      <nldd-text-field
        ref={searchRef}
        value={searchQuery}
        placeholder="Zoek op naam, e-mail of functie..."
        accessible-label="Zoek personen"
      />

      {/* Merge bar: merging moves roles and placements, super_admin-only */}
      {isSuperAdmin && selectedIds.size >= 2 && !showMergeConfirm && (
        <nldd-banner variant="accent" size="sm" text={`${selectedIds.size} personen geselecteerd`}>
          <div slot="actions">
            <NlddButton
              text="Samenvoegen"
              startIcon="git-merge"
              size="sm"
              onClick={() => setShowMergeConfirm(true)}
            />
            <NlddButton
              text="Deselecteren"
              variant="neutral-transparent"
              size="sm"
              onClick={() => {
                setSelectedIds(new Set());
                setMergeTargetId(null);
              }}
            />
          </div>
        </nldd-banner>
      )}

      {/* Merge confirmation */}
      {showMergeConfirm && (
        <nldd-banner
          variant="warning"
          text="Welke persoon wil je behouden?"
          supporting-text="Alle referenties van de andere worden overgeheveld."
        >
          <nldd-radio-button-group
            ref={mergeTargetGroupRef}
            name="merge-target"
            accessible-label="Te behouden persoon"
          >
            {selectedPeople.map((p) => (
              <nldd-radio-button-field
                key={p.id}
                value={p.id}
                checked={mergeTargetId === p.id ? true : undefined}
                label={`${p.naam}${p.email ? ` (${p.email})` : ''}${p.functie ? ` - ${formatFunctie(p.functie)}` : ''}`}
              />
            ))}
          </nldd-radio-button-group>
          <div slot="actions">
            <NlddButton
              text={merge.isPending ? 'Samenvoegen...' : 'Bevestig samenvoegen'}
              startIcon="git-merge"
              variant="destructive"
              size="sm"
              disabled={merge.isPending || !mergeTargetId}
              onClick={handleMerge}
            />
            <NlddButton
              text="Annuleren"
              variant="neutral-tinted"
              size="sm"
              disabled={merge.isPending}
              onClick={() => setShowMergeConfirm(false)}
            />
          </div>
        </nldd-banner>
      )}

      {/* People list with expandable role panels */}
      {/* `selectable` because the rows carry a selection checkbox: without it
          the table deliberately omits aria-selected, so assistive technology is
          not told about a selection state it would otherwise announce. */}
      <nldd-table
        columns="48px minmax(140px,1fr) 200px 160px 140px"
        sm-columns="48px 1fr 140px"
        md-columns="48px 1fr 200px 140px"
        accessible-label="Personen en roltoewijzingen"
        selectable
      >
        <nldd-table-row slot="header">
          <nldd-text-cell />
          <nldd-text-cell text="Naam" />
          <nldd-text-cell text="E-mail" hide-below="md" />
          <nldd-text-cell text="Functie" hide-below="lg" />
          <nldd-text-cell text="Laatst actief" />
        </nldd-table-row>
        {filteredPeople.map((person) => {
          const isExpanded = expandedPersonId === person.id;
          return (
            <PersonRow
              key={person.id}
              personId={person.id}
              naam={person.naam}
              email={person.email}
              functie={person.functie}
              lastSeenAt={person.last_seen_at}
              isAgent={person.is_agent}
              isExpanded={isExpanded}
              isSelf={authPerson?.id === person.id}
              selected={selectedIds.has(person.id)}
              onToggleSelect={() => toggleSelected(person.id)}
              onToggle={() => setExpandedPersonId(isExpanded ? null : person.id)}
            />
          );
        })}
        <div slot="empty">
          <EmptyState
            icon="magnifier"
            title={searchQuery ? 'Geen personen gevonden' : 'Geen personen beschikbaar'}
            description={searchQuery ? 'Pas je zoekopdracht aan.' : undefined}
          />
        </div>
      </nldd-table>
    </nldd-container>
  );
}

function PersonRow({
  personId,
  naam,
  email,
  functie,
  lastSeenAt,
  isAgent,
  isExpanded,
  isSelf,
  selected,
  onToggleSelect,
  onToggle,
}: {
  personId: string;
  naam: string;
  email?: string;
  functie?: string;
  lastSeenAt?: string | null;
  isAgent?: boolean;
  isExpanded: boolean;
  isSelf: boolean;
  selected: boolean;
  onToggleSelect: () => void;
  onToggle: () => void;
}) {
  const online = isPersonOnline({ last_seen_at: lastSeenAt, is_agent: isAgent });
  const checkboxRef = useRef<HTMLElement>(null);
  useNlddEvent(checkboxRef, 'change', onToggleSelect);

  return (
    // `selected` both highlights the row and, because the table is `selectable`,
    // drives its aria-selected.
    <nldd-table-row selected={selected ? true : undefined}>
      <nldd-text-cell>
        <nldd-checkbox
          ref={checkboxRef}
          checked={selected ? true : undefined}
          accessible-label={`${naam} selecteren voor samenvoegen`}
        />
      </nldd-text-cell>
      <nldd-text-cell>
        <NlddButton
          variant="neutral-transparent"
          size="sm"
          text={isSelf ? `${naam} (jij)` : naam}
          startIcon={isExpanded ? 'chevron-down' : 'chevron-right'}
          onClick={onToggle}
        />
      </nldd-text-cell>
      <nldd-text-cell text={email || '-'} color="secondary" hide-below="md" />
      <nldd-text-cell text={formatFunctie(functie) || '-'} color="secondary" hide-below="lg" />
      <nldd-text-cell>
        {online ? (
          <nldd-tag text="Nu actief" color="success" size="sm" />
        ) : (
          <nldd-text size="sm" color="secondary">{formatRelativeTime(lastSeenAt)}</nldd-text>
        )}
      </nldd-text-cell>
      {isExpanded && (
        <div style={{ gridColumn: '1 / -1' }}>
          <PersonRolesPanel personId={personId} />
        </div>
      )}
    </nldd-table-row>
  );
}
