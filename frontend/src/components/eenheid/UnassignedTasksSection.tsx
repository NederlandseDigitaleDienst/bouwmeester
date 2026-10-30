import { useMemo, useRef, useState } from 'react';
import { Badge } from '@/components/common/Badge';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { Icon } from '@/components/nldd/Icon';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import { useUpdateTask } from '@/hooks/useTasks';
import { useOrganisatieFlat, useOrganisatiePersonenRecursive } from '@/hooks/useOrganisatie';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { buildPersonOptions } from '@/utils/personOptions';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { isOverdue as checkOverdue, formatDateShort } from '@/utils/dates';
import {
  TASK_PRIORITY_LABELS,
  TASK_PRIORITY_COLORS,
  formatOrganisatieType,
} from '@/types';
import type { Task, Person, OrganisatieEenheidPersonenGroup } from '@/types';
import { formatFunctie } from '@/types';
import type { SelectOption } from '@/components/common/CreatableSelect';

const PERSON_LEVEL_TYPES = new Set(['afdeling', 'dienst', 'bureau', 'cluster', 'team']);

function flattenPersonenGroup(group: OrganisatieEenheidPersonenGroup): Person[] {
  const people = [...group.personen];
  for (const child of group.children) {
    people.push(...flattenPersonenGroup(child));
  }
  return people;
}

function getDescendantIds(allUnits: { id: string; parent_id?: string | null }[], parentId: string): Set<string> {
  const descendants = new Set<string>();
  const queue = [parentId];
  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const u of allUnits) {
      if (u.parent_id === current && !descendants.has(u.id)) {
        descendants.add(u.id);
        queue.push(u.id);
      }
    }
  }
  return descendants;
}

interface UnassignedTasksSectionProps {
  noUnitTasks: Task[];
  noUnitCount: number;
  noPersonTasks: Task[];
  noPersonCount: number;
  eenheidType: string;
  selectedEenheidId: string;
}

interface DisclosureHeaderProps {
  icon: string;
  label: string;
  count: number;
  open: boolean;
  onToggle: () => void;
}

/**
 * A section header that opens/closes a group of rows below it. This is the
 * disclosure-row shape from the list-with-rows pattern (a `button` row with
 * cells), not `NlddButton`: that wrapper's children only reach the button's
 * `text` slot, which cannot hold a chevron + icon + label + count tag — it
 * has no default slot for arbitrary content.
 */
function DisclosureHeader({ icon, label, count, open, onToggle }: DisclosureHeaderProps) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', onToggle);

  return (
    <nldd-list-item ref={ref} button expanded={orUndef(open)}>
      <nldd-icon-cell icon={open ? 'chevron-down' : 'chevron-right'} size="16" />
      <nldd-spacer-cell size="8" />
      <nldd-icon-cell icon={icon} size="16" />
      <nldd-spacer-cell size="8" />
      {/* nldd-text-cell has no weight attribute; **bold** in `text` is how the
          cell expresses inline emphasis. */}
      <nldd-text-cell text={`**${label}**`} color="secondary" width="fit-content" />
      <nldd-spacer-cell size="8" />
      <nldd-cell>
        <nldd-tag text={String(count)} color="warning" size="sm" />
      </nldd-cell>
    </nldd-list-item>
  );
}

function TaskRow({ task, showPersonAssign, selectedEenheidId, personOptions }: { task: Task; showPersonAssign: boolean; selectedEenheidId: string; personOptions: SelectOption[] }) {
  const { openTaskDetail } = useTaskDetail();
  const updateTask = useUpdateTask();
  const { data: eenheden } = useOrganisatieFlat();

  const isOverdue = task.due_date && checkOverdue(task.due_date);

  const eenheidOptions: SelectOption[] = useMemo(() => {
    const all = eenheden ?? [];
    const descendantIds = selectedEenheidId ? getDescendantIds(all, selectedEenheidId) : new Set<string>();
    const filtered = selectedEenheidId
      ? all.filter((e) => descendantIds.has(e.id))
      : all;
    return [
      { value: '', label: 'Geen' },
      ...filtered.map((e) => ({
        value: e.id,
        label: e.naam,
        description: formatOrganisatieType(e.type),
      })),
    ];
  }, [eenheden, selectedEenheidId]);

  const handleUnitChange = (value: string) => {
    updateTask.mutate({
      id: task.id,
      data: { organisatie_eenheid_id: value || null },
    });
  };

  const handlePersonChange = (value: string) => {
    updateTask.mutate({
      id: task.id,
      data: { assignee_id: value || null },
    });
  };

  const titleRef = useRef<HTMLElement>(null);
  useNlddEvent(titleRef, 'click', () => openTaskDetail(task.id));

  return (
    // A row-with-controls in a card, not an nldd-list row: each task carries
    // two live CreatableSelect dropdowns rather than a fixed action set, which
    // the list/segment composition is not meant for. Its shape changes at the
    // md breakpoint, which nldd-container cannot express, so the row itself is
    // a class in utilities.css.
    <div className="unassigned-task-row hover-tinted">
      <nldd-container width="full" min-width="0" gap="4">
        {/* nldd-button rather than the NlddButton wrapper: this needs
            width="full" + left alignment, which the wrapper does not expose.

            `single-line` because a task title is a sentence, and without it
            the label wraps. In the narrow column left over beside the two
            224px dropdowns that becomes one word per line, a column of text
            the row grows to fit. */}
        <nldd-button
          ref={titleRef}
          text={task.title}
          appearance="neutral-transparent"
          size="sm"
          width="full"
          single-line
          horizontal-alignment="left"
        />
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <Badge
            color={TASK_PRIORITY_COLORS[task.priority]}
            dot
          >
            {TASK_PRIORITY_LABELS[task.priority]}
          </Badge>
          {task.due_date && (
            <nldd-container layout="row" gap="4" vertical-alignment="center">
              <Icon name="clock" size="xs" />
              <nldd-text size="xs" color={isOverdue ? 'critical' : 'secondary'} weight={isOverdue ? 'bold' : 'regular'}>
                {formatDateShort(task.due_date)}
              </nldd-text>
            </nldd-container>
          )}
        </nldd-container>
      </nldd-container>
      {/* shrink-0 keeps this pair from being squeezed by the title container's
          own width="full" above (nldd-container has no flex-shrink
          attribute). The two selects below keep their md-breakpoint caveat
          from the outer row: nldd-container's width is not responsive. */}
      <nldd-container layout="row" gap="8" vertical-alignment="center" className="shrink-0">
        <div className="unassigned-task-field">
          <CreatableSelect
            value={task.organisatie_eenheid_id ?? ''}
            onChange={handleUnitChange}
            options={eenheidOptions}
            placeholder="Eenheid..."
          />
        </div>
        {showPersonAssign && (
          <div className="unassigned-task-field">
            <CreatableSelect
              value={task.assignee_id ?? ''}
              onChange={handlePersonChange}
              options={personOptions}
              placeholder="Persoon..."
            />
          </div>
        )}
      </nldd-container>
    </div>
  );
}

export function UnassignedTasksSection({
  noUnitTasks,
  noUnitCount,
  noPersonTasks,
  noPersonCount,
  eenheidType,
  selectedEenheidId,
}: UnassignedTasksSectionProps) {
  const [noUnitOpen, setNoUnitOpen] = useState(true);
  const [noPersonOpen, setNoPersonOpen] = useState(true);
  const { currentPerson } = useCurrentPerson();
  const { data: personenGroup } = useOrganisatiePersonenRecursive(selectedEenheidId || null);

  const personOptions: SelectOption[] = useMemo(() => {
    if (!personenGroup) return [];
    const people = flattenPersonenGroup(personenGroup);
    const seen = new Set<string>();
    const unique = people.filter((p) => {
      if (seen.has(p.id)) return false;
      seen.add(p.id);
      return true;
    });
    return buildPersonOptions(unique, currentPerson, (p) => ({
      value: p.id,
      label: p.naam,
      description: formatFunctie(p.functie),
    }));
  }, [personenGroup, currentPerson]);

  const isPersonLevel = PERSON_LEVEL_TYPES.has(eenheidType);
  const showNoPersonSection = isPersonLevel;
  const totalCount = noUnitCount + (showNoPersonSection ? noPersonCount : 0);
  if (totalCount === 0) return null;

  return (
    <nldd-card>
      <nldd-container layout="row" gap="12" vertical-alignment="center" padding="20">
        {/* Fixed 40px square icon badge: same case as InboxItem's type icon —
            nldd-container has no fixed-height/border-radius attributes, so the
            box stays plain CSS. The color is a warning token, not a hex value. */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '40px',
            width: '40px',
            flexShrink: 0,
            borderRadius: 'var(--primitives-corner-radius-md)',
            background: 'var(--primitives-color-warning-100)',
            color: 'var(--primitives-color-warning-600)',
          }}
        >
          <Icon name="exclamation-triangle" size="lg" />
        </div>
        <nldd-container gap="0">
          <nldd-text size="md" weight="bold">Onverdeeld</nldd-text>
          <nldd-text size="sm" color="secondary">
            {totalCount} {totalCount === 1 ? 'taak' : 'taken'} zonder toewijzing
          </nldd-text>
        </nldd-container>
      </nldd-container>

      {/* No unit section */}
      {noUnitCount > 0 && (
        <nldd-container>
          <nldd-divider />
          <DisclosureHeader
            icon="apartment-building"
            label="Geen eenheid"
            count={noUnitCount}
            open={noUnitOpen}
            onToggle={() => setNoUnitOpen(!noUnitOpen)}
          />
          {noUnitOpen && (
            <nldd-container>
              {noUnitTasks.map((task) => (
                <TaskRow key={task.id} task={task} showPersonAssign={false} selectedEenheidId={selectedEenheidId} personOptions={personOptions} />
              ))}
              {noUnitCount > noUnitTasks.length && (
                <nldd-container padding="20" padding-block="8">
                  <nldd-text size="xs" color="secondary">
                    En nog {noUnitCount - noUnitTasks.length} meer...
                  </nldd-text>
                </nldd-container>
              )}
            </nldd-container>
          )}
        </nldd-container>
      )}

      {/* No person section — only at afdeling/team level */}
      {showNoPersonSection && noPersonCount > 0 && (
        <nldd-container>
          <nldd-divider />
          <DisclosureHeader
            icon="person"
            label="Geen persoon"
            count={noPersonCount}
            open={noPersonOpen}
            onToggle={() => setNoPersonOpen(!noPersonOpen)}
          />
          {noPersonOpen && (
            <nldd-container>
              {noPersonTasks.map((task) => (
                <TaskRow key={task.id} task={task} showPersonAssign={isPersonLevel} selectedEenheidId={selectedEenheidId} personOptions={personOptions} />
              ))}
              {noPersonCount > noPersonTasks.length && (
                <nldd-container padding="20" padding-block="8">
                  <nldd-text size="xs" color="secondary">
                    En nog {noPersonCount - noPersonTasks.length} meer...
                  </nldd-text>
                </nldd-container>
              )}
            </nldd-container>
          )}
        </nldd-container>
      )}
    </nldd-card>
  );
}
