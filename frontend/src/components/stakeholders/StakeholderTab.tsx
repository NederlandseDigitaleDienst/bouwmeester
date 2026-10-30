import { useEffect, useMemo, useRef, useState } from 'react';
import { Badge } from '@/components/common/Badge';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Select } from '@/components/common/Select';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent, useNlddValue } from '@/components/nldd/events';
import {
  useStakeholderAssessments,
  useCreateStakeholderAssessment,
  useUpdateStakeholderAssessment,
  useDeleteStakeholderAssessment,
} from '@/hooks/useStakeholderAssessments';
import { usePeople } from '@/hooks/usePeople';
import { STAKEHOLDER_HOUDING_LABELS } from '@/types';
import type {
  StakeholderAssessment,
  StakeholderHouding,
  StakeholderScopeType,
  EntityColor,
} from '@/types';

interface StakeholderTabProps {
  scopeType: StakeholderScopeType;
  scopeId: string;
  readOnly?: boolean;
}

const HOUDING_OPTIONS: StakeholderHouding[] = [
  'tegen',
  'kritisch',
  'neutraal',
  'welwillend',
  'voorstander',
];

const SCORE_OPTIONS = [1, 2, 3, 4, 5];

// '' is a real, selectable "no value" option here, so it is part of the list
// rather than Select's disabled placeholder.
const EMPTY_OPTION = { value: '', label: '—' };
const SCORE_SELECT_OPTIONS = [
  EMPTY_OPTION,
  ...SCORE_OPTIONS.map((n) => ({ value: String(n), label: String(n) })),
];
const HOUDING_SELECT_OPTIONS = [
  EMPTY_OPTION,
  ...HOUDING_OPTIONS.map((h) => ({ value: h, label: STAKEHOLDER_HOUDING_LABELS[h] })),
];

/** Houding -> Badge color. */
const HOUDING_BADGE_COLOR: Record<StakeholderHouding, EntityColor> = {
  tegen: 'rood',
  kritisch: 'oranje',
  neutraal: 'donkerblauw',
  welwillend: 'mosgroen',
  voorstander: 'groen',
};

export function StakeholderTab({
  scopeType,
  scopeId,
  readOnly = false,
}: StakeholderTabProps) {
  const { data: assessments = [], isLoading } = useStakeholderAssessments(
    scopeType,
    scopeId,
  );
  const { data: allPeople = [] } = usePeople();
  const createMutation = useCreateStakeholderAssessment();
  const updateMutation = useUpdateStakeholderAssessment();
  const deleteMutation = useDeleteStakeholderAssessment();
  const [addValue, setAddValue] = useState('');

  const availableOptions = useMemo(() => {
    const linkedIds = new Set(assessments.map((a) => a.person_id));
    return allPeople
      .filter((p) => !linkedIds.has(p.id) && !p.is_agent)
      .map((p) => ({ value: p.id, label: p.naam }));
  }, [allPeople, assessments]);

  const handleAdd = async (personId: string) => {
    if (!personId) return;
    await createMutation.mutateAsync({
      person_id: personId,
      scope_type: scopeType,
      scope_id: scopeId,
    });
    setAddValue('');
  };

  const handleUpdate = (
    a: StakeholderAssessment,
    patch: Partial<StakeholderAssessment>,
  ) => {
    updateMutation.mutate({
      id: a.id,
      data: patch,
      scopeType,
      scopeId,
    });
  };

  const handleDelete = (a: StakeholderAssessment) => {
    deleteMutation.mutate({ id: a.id, scopeType, scopeId });
  };

  if (isLoading) {
    return (
      <nldd-container padding-block="24">
        <LoadingSpinner />
      </nldd-container>
    );
  }

  return (
    <nldd-container gap="12">
      {assessments.length === 0 ? (
        <nldd-text size="sm" color="secondary">
          Nog geen stakeholders geregistreerd.
        </nldd-text>
      ) : (
        <nldd-list type="form" appearance="box-tinted" accessible-label="Stakeholders">
          {assessments.map((a) => (
            <nldd-list-item key={a.id}>
              {/* A row this complex (name, delete action, three selects, a
                  note editor) is more than text-cell can carry, so it goes in
                  a single full-width nldd-cell per the "multiple paragraphs
                  or markup in a row" guidance from the list-with-rows pattern. */}
              <nldd-cell width="full">
                <nldd-container gap="8" padding-block="4">
                  <nldd-container layout="row" gap="8" vertical-alignment="center">
                    <nldd-text weight="medium" size="sm">{a.person_naam}</nldd-text>
                    <nldd-spacer size="flexible" />
                    {!readOnly && (
                      <NlddIconButton
                        icon="trash"
                        accessibleLabel="Stakeholder verwijderen"
                        variant="neutral-transparent"
                        size="sm"
                        onClick={() => handleDelete(a)}
                      />
                    )}
                  </nldd-container>
                  <nldd-container layout="grid" column-count={3} gap="8">
                    <ScoreSelect
                      label="Belang"
                      value={a.belang}
                      onChange={(v) => handleUpdate(a, { belang: v })}
                      disabled={readOnly}
                    />
                    <HoudingSelect
                      value={a.houding}
                      onChange={(v) => handleUpdate(a, { houding: v })}
                      disabled={readOnly}
                    />
                    <ScoreSelect
                      label="Invloed"
                      value={a.invloed}
                      onChange={(v) => handleUpdate(a, { invloed: v })}
                      disabled={readOnly}
                    />
                  </nldd-container>
                  {!readOnly && (
                    <NoteEditor
                      value={a.notitie}
                      onPersist={(value) => handleUpdate(a, { notitie: value })}
                    />
                  )}
                  {readOnly && a.notitie && (
                    <RichTextDisplay content={a.notitie} fallback="" />
                  )}
                </nldd-container>
              </nldd-cell>
            </nldd-list-item>
          ))}
        </nldd-list>
      )}

      {!readOnly && (
        <nldd-container width="full">
          <CreatableSelect
            value={addValue}
            onChange={(v) => {
              setAddValue(v);
              if (v) handleAdd(v);
            }}
            options={availableOptions}
            placeholder="Persoon toevoegen..."
          />
        </nldd-container>
      )}
    </nldd-container>
  );
}

function ScoreSelect({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  disabled?: boolean;
}) {
  return (
    <nldd-form-field label={label}>
      <Select
        aria-label={label}
        size="sm"
        value={value == null ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        disabled={disabled}
        options={SCORE_SELECT_OPTIONS}
      />
    </nldd-form-field>
  );
}

function HoudingSelect({
  value,
  onChange,
  disabled,
}: {
  value: StakeholderHouding | null;
  onChange: (v: StakeholderHouding | null) => void;
  disabled?: boolean;
}) {
  if (disabled) {
    return (
      <nldd-container gap="2">
        <nldd-text size="xs" color="secondary">Houding</nldd-text>
        {value ? (
          <Badge color={HOUDING_BADGE_COLOR[value]}>
            {STAKEHOLDER_HOUDING_LABELS[value]}
          </Badge>
        ) : (
          <nldd-text size="sm" color="secondary">—</nldd-text>
        )}
      </nldd-container>
    );
  }

  return (
    <nldd-form-field label="Houding">
      <Select
        aria-label="Houding"
        size="sm"
        value={value ?? ''}
        onChange={(e) =>
          onChange(e.target.value === '' ? null : (e.target.value as StakeholderHouding))
        }
        options={HOUDING_SELECT_OPTIONS}
      />
    </nldd-form-field>
  );
}

function NoteEditor({
  value,
  onPersist,
}: {
  value: string | null;
  onPersist: (v: string | null) => void;
}) {
  // Local draft so typing doesn't fire a PUT per keystroke. Persist on blur.
  // Sync from server only when not actively editing.
  const [draft, setDraft] = useState(value ?? '');
  const [focused, setFocused] = useState(false);
  const ref = useRef<HTMLElement & { value?: string }>(null);

  useEffect(() => {
    if (!focused) {
      setDraft(value ?? '');
    }
  }, [value, focused]);

  useNlddValue(ref, draft);
  useNlddEvent(ref, 'input', (e) => setDraft(eventValue(e)));
  useNlddEvent(ref, 'focus', () => setFocused(true));
  useNlddEvent(ref, 'blur', () => {
    setFocused(false);
    const next = draft.trim() ? draft : null;
    if (next !== (value ?? null)) {
      onPersist(next);
    }
  });

  return (
    <nldd-multi-line-text-field
      ref={ref}
      placeholder="Notitie (optioneel)"
      rows={2}
      accessible-label="Notitie"
    />
  );
}
