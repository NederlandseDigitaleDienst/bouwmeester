import { useMemo, useState } from 'react';
import { Badge } from '@/components/common/Badge';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { Select } from '@/components/common/Select';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import {
  useAddInitiatiefMember,
  useRemoveInitiatiefMember,
  useUpdateInitiatiefMemberRole,
  useAddInitiatiefEenheid,
  useRemoveInitiatiefEenheid,
  useUpdateInitiatiefEenheidRol,
} from '@/hooks/useInitiatieven';
import { usePeople } from '@/hooks/usePeople';
import { useOrganisatieFlat } from '@/hooks/useOrganisatie';
import { INITIATIEF_ROL_LABELS } from '@/types';
import type { InitiatiefDetail } from '@/types';
import { StakeholderTab } from '@/components/stakeholders/StakeholderTab';
import { SectionHeading } from './SectionHeading';
import { NlddButton } from '@/components/nldd/NlddButton';

/**
 * The "Mensen" tab: who works on the initiatief (members and eenheden, which
 * both grant access) and who has a stake in it (stakeholders, which grant
 * nothing). Only an eigenaar changes membership; contributors can assess
 * stakeholders.
 */
export function InitiatiefMensen({ initiatief }: { initiatief: InitiatiefDetail }) {
  const isEigenaar = initiatief.access_level === 'eigenaar';
  const canEdit = isEigenaar || initiatief.access_level === 'contributor';

  return (
    <nldd-container gap="32">
      <Members initiatief={initiatief} isEigenaar={isEigenaar} />
      <Eenheden initiatief={initiatief} isEigenaar={isEigenaar} />
      <nldd-container gap="8">
        <SectionHeading icon="person" text="Stakeholders" />
        <StakeholderTab scopeType="initiatief" scopeId={initiatief.id} readOnly={!canEdit} />
      </nldd-container>
    </nldd-container>
  );
}

function Members({ initiatief, isEigenaar }: { initiatief: InitiatiefDetail; isEigenaar: boolean }) {
  const addMemberMutation = useAddInitiatiefMember();
  const removeMemberMutation = useRemoveInitiatiefMember();
  const updateRoleMutation = useUpdateInitiatiefMemberRole();
  const { data: allPeople = [] } = usePeople();
  const [addMemberValue, setAddMemberValue] = useState('');

  const eigenaarCount = initiatief.members.filter((m) => m.rol === 'eigenaar').length;

  const availablePeopleOptions = useMemo(() => {
    const memberIds = new Set(initiatief.members.map((m) => m.person_id));
    return allPeople
      .filter((p) => !memberIds.has(p.id) && !p.is_agent)
      .map((p) => ({ value: p.id, label: p.naam }));
  }, [allPeople, initiatief.members]);

  const handleAddMember = async (personId: string) => {
    if (!personId) return;
    await addMemberMutation.mutateAsync({ initiatiefId: initiatief.id, personId });
    setAddMemberValue('');
  };

  const setRole = (personId: string, rol: 'eigenaar' | 'contributor') =>
    updateRoleMutation.mutateAsync({ initiatiefId: initiatief.id, personId, rol });

  return (
    <nldd-container gap="8">
      <SectionHeading icon="users" text={`Leden (${initiatief.members.length})`} />

      {initiatief.members.length > 0 && (
        <nldd-list type="list" appearance="box-tinted">
          {initiatief.members.map((member) => (
            <nldd-list-item key={member.person_id}>
              <nldd-container layout="row" width="full" gap="8" horizontal-alignment="right" vertical-alignment="center">
                <nldd-container layout="row" gap="8" vertical-alignment="center">
                  <nldd-text-cell text={member.person_naam} width="fit-content" />
                  <Badge color={member.rol === 'eigenaar' ? 'paars' : 'coolgray'}>
                    {INITIATIEF_ROL_LABELS[member.rol] ?? member.rol}
                  </Badge>
                </nldd-container>
                {isEigenaar && (
                  <div className="hug">
                    {member.rol === 'eigenaar' ? (
                      eigenaarCount > 1 && (
                        <NlddButton variant="neutral-transparent" size="sm" onClick={() => setRole(member.person_id, 'contributor')} text="Maak bijdrager" />
                      )
                    ) : (
                      <>
                        <NlddButton variant="neutral-transparent" size="sm" onClick={() => setRole(member.person_id, 'eigenaar')} text="Maak eigenaar" />
                        <NlddIconButton
                          icon="close"
                          accessibleLabel={`${member.person_naam} verwijderen`}
                          variant="neutral-transparent"
                          size="sm"
                          onClick={() =>
                            removeMemberMutation.mutateAsync({
                              initiatiefId: initiatief.id,
                              personId: member.person_id,
                            })
                          }
                        />
                      </>
                    )}
                  </div>
                )}
              </nldd-container>
            </nldd-list-item>
          ))}
        </nldd-list>
      )}

      {isEigenaar && (
        <nldd-container layout="row" gap="8" vertical-alignment="top">
          <nldd-container width="fit-content" className="row-fill">
            <CreatableSelect
              value={addMemberValue}
              onChange={(val) => {
                setAddMemberValue(val);
                if (val) handleAddMember(val);
              }}
              options={availablePeopleOptions}
              placeholder="Lid toevoegen..."
              emptyMessage="Geen personen gevonden"
            />
          </nldd-container>
          <NlddButton
            variant="secondary"
            size="sm"
            startIcon="person-badge-plus"
            onClick={() => {
              if (addMemberValue) handleAddMember(addMemberValue);
            }}
            disabled={!addMemberValue}
            text="Toevoegen"
          />
        </nldd-container>
      )}
    </nldd-container>
  );
}

function Eenheden({ initiatief, isEigenaar }: { initiatief: InitiatiefDetail; isEigenaar: boolean }) {
  const addEenheidMutation = useAddInitiatiefEenheid();
  const removeEenheidMutation = useRemoveInitiatiefEenheid();
  const updateEenheidRolMutation = useUpdateInitiatiefEenheidRol();
  const { data: allEenheden = [] } = useOrganisatieFlat();
  const [addEenheidValue, setAddEenheidValue] = useState('');

  const availableEenheidOptions = useMemo(() => {
    const linked = new Set(initiatief.eenheden.map((e) => e.eenheid_id));
    return allEenheden
      .filter((e) => !linked.has(e.id))
      .map((e) => ({ value: e.id, label: e.naam }));
  }, [allEenheden, initiatief.eenheden]);

  const handleAddEenheid = async (eenheidId: string) => {
    if (!eenheidId) return;
    await addEenheidMutation.mutateAsync({ initiatiefId: initiatief.id, eenheidId });
    setAddEenheidValue('');
  };

  // Without an eigenaar to add one, an empty list is only noise.
  if (!isEigenaar && initiatief.eenheden.length === 0) return null;

  return (
    <nldd-container gap="8">
      <SectionHeading icon="apartment-building" text={`Organisatie-eenheden (${initiatief.eenheden.length})`} />
      <nldd-text size="xs" color="secondary">
        Iedereen in een gekoppelde eenheid krijgt de rol die hier naast de eenheid staat.
      </nldd-text>

      {initiatief.eenheden.length > 0 && (
        <nldd-list type="list" appearance="box-tinted">
          {initiatief.eenheden.map((eenheid) => (
            <nldd-list-item key={eenheid.eenheid_id}>
              <nldd-container layout="row" width="full" gap="8" vertical-alignment="center">
                {/* The name takes what the role column leaves. With
                    `fit-content` and no floor it shrank to within a word:
                    "RegelRecht" broke as "RegelRec/ht". */}
                <nldd-text-cell text={eenheid.eenheid_naam} width="full" />
                {/* A fixed width for the role column. `fit-content` gave it
                    nothing of its own to measure, so it collapsed to zero and
                    drew the select's chevrons and the delete cross on top of
                    each other at the row's edge. */}
                <nldd-container
                  layout="row"
                  width={isEigenaar ? '200px' : '120px'}
                  className="shrink-0"
                  gap="6"
                  vertical-alignment="center"
                  horizontal-alignment="right"
                >
                  {isEigenaar ? (
                    <nldd-container width="160px">
                      <Select
                        value={eenheid.rol}
                        aria-label="Rol van deze eenheid"
                        onChange={(e) =>
                          updateEenheidRolMutation.mutateAsync({
                            initiatiefId: initiatief.id,
                            eenheidId: eenheid.eenheid_id,
                            rol: e.target.value,
                          })
                        }
                        options={Object.entries(INITIATIEF_ROL_LABELS).map(([value, label]) => ({
                          value,
                          label,
                        }))}
                      />
                    </nldd-container>
                  ) : (
                    <nldd-tag color="neutral" size="sm" text={INITIATIEF_ROL_LABELS[eenheid.rol] ?? eenheid.rol} />
                  )}
                  {isEigenaar && (
                    <NlddIconButton
                      icon="close"
                      accessibleLabel={`${eenheid.eenheid_naam} verwijderen`}
                      variant="neutral-transparent"
                      size="sm"
                      onClick={() =>
                        removeEenheidMutation.mutateAsync({
                          initiatiefId: initiatief.id,
                          eenheidId: eenheid.eenheid_id,
                        })
                      }
                    />
                  )}
                </nldd-container>
              </nldd-container>
            </nldd-list-item>
          ))}
        </nldd-list>
      )}

      {isEigenaar && (
        <nldd-container layout="row" gap="8" vertical-alignment="top">
          <nldd-container width="fit-content" className="row-fill">
            <CreatableSelect
              value={addEenheidValue}
              onChange={(val) => {
                setAddEenheidValue(val);
                if (val) handleAddEenheid(val);
              }}
              options={availableEenheidOptions}
              placeholder="Eenheid toevoegen..."
              emptyMessage="Geen eenheden gevonden"
            />
          </nldd-container>
          <NlddButton
            variant="secondary"
            size="sm"
            startIcon="apartment-building"
            onClick={() => {
              if (addEenheidValue) handleAddEenheid(addEenheidValue);
            }}
            disabled={!addEenheidValue}
            text="Toevoegen"
          />
        </nldd-container>
      )}
    </nldd-container>
  );
}
