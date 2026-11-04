import { useCallback, useMemo, useRef, useState } from 'react';
import { Select } from '@/components/common/Select';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, orUndef, useNlddEvent } from '@/components/nldd/events';
import {
  useCreateLeadColumn,
  useDeleteLeadColumn,
  useLeadColumns,
  useReorderLeadColumns,
  useUpdateLeadColumn,
} from '@/hooks/useLeadColumns';
import type { LeadColumn } from '@/types';
import { leadColumnTagColor } from './stageColors';
import { NlddButton } from '@/components/nldd/NlddButton';

type NlddTagColor = NonNullable<React.ComponentProps<'nldd-tag'>['color']>;

type NlddIconColor = NonNullable<React.ComponentProps<'nldd-icon'>['color']>;

/**
 * The closed set of nldd-tag color names `LeadColumn.color` may hold,
 * mirrored from backend `schema.lead_column.LEAD_COLUMN_COLORS` (kept in
 * sync by hand). The swatch is an nldd-icon in that color: the icon takes the
 * same Rijkshuisstijl names and semantic roles as the tag, except that its
 * grey is 'secondary-content' rather than 'neutral'.
 */
const COLOR_PRESETS: { label: string; value: NlddTagColor }[] = [
  // Semantic roles
  { label: 'Neutraal', value: 'neutral' },
  { label: 'Accent', value: 'accent' },
  { label: 'Succes', value: 'success' },
  { label: 'Waarschuwing', value: 'warning' },
  { label: 'Kritiek', value: 'critical' },
  // Rijkshuisstijl
  { label: 'Lintblauw', value: 'lintblauw' },
  { label: 'Donkerblauw', value: 'donkerblauw' },
  { label: 'Hemelblauw', value: 'hemelblauw' },
  { label: 'Lichtblauw', value: 'lichtblauw' },
  { label: 'Paars', value: 'paars' },
  { label: 'Violet', value: 'violet' },
  { label: 'Robijnrood', value: 'robijnrood' },
  { label: 'Roze', value: 'roze' },
  { label: 'Rood', value: 'rood' },
  { label: 'Oranje', value: 'oranje' },
  { label: 'Donkergeel', value: 'donkergeel' },
  { label: 'Geel', value: 'geel' },
  { label: 'Donkerbruin', value: 'donkerbruin' },
  { label: 'Bruin', value: 'bruin' },
  { label: 'Donkergroen', value: 'donkergroen' },
  { label: 'Groen', value: 'groen' },
  { label: 'Mosgroen', value: 'mosgroen' },
  { label: 'Mintgroen', value: 'mintgroen' },
];

interface ColumnsManagerProps {
  initiatiefId: string;
}

export function ColumnsManager({ initiatiefId }: ColumnsManagerProps) {
  const { columns, isLoading } = useLeadColumns(initiatiefId);
  const createMutation = useCreateLeadColumn(initiatiefId);
  const updateMutation = useUpdateLeadColumn(initiatiefId);
  const deleteMutation = useDeleteLeadColumn(initiatiefId);
  const reorderMutation = useReorderLeadColumns(initiatiefId);

  const [adding, setAdding] = useState(false);
  const [draftName, setDraftName] = useState('');
  const draftNameRef = useRef<HTMLElement>(null);
  // `input` rather than `change`: a controlled field has to follow every
  // keystroke, or "Toevoegen" only enables after the field loses focus.
  useNlddEvent(draftNameRef, 'input', (event) => setDraftName(eventValue(event) ?? ''));
  const [draftColor, setDraftColor] = useState(COLOR_PRESETS[0].value);
  const [editing, setEditing] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [moveTarget, setMoveTarget] = useState<string>('');

  const sortedColumns = useMemo(
    () => [...columns].sort((a, b) => a.sort_order - b.sort_order),
    [columns],
  );

  const deletingColumn = sortedColumns.find((c) => c.id === deletingId) ?? null;
  const otherColumns = sortedColumns.filter((c) => c.id !== deletingId);

  const handleAdd = async () => {
    const name = draftName.trim();
    if (!name) return;
    await createMutation.mutateAsync({ name, color: draftColor });
    setDraftName('');
    setDraftColor(COLOR_PRESETS[0].value);
    setAdding(false);
  };

  const startEdit = (col: LeadColumn) => {
    setEditing(col.id);
    setEditName(col.name);
  };

  const commitEdit = async () => {
    if (!editing) return;
    const name = editName.trim();
    if (!name) {
      setEditing(null);
      return;
    }
    await updateMutation.mutateAsync({ id: editing, data: { name } });
    setEditing(null);
  };

  const moveColumn = async (col: LeadColumn, dir: 'up' | 'down') => {
    const idx = sortedColumns.findIndex((c) => c.id === col.id);
    const targetIdx = dir === 'up' ? idx - 1 : idx + 1;
    if (targetIdx < 0 || targetIdx >= sortedColumns.length) return;
    const next = [...sortedColumns];
    [next[idx], next[targetIdx]] = [next[targetIdx], next[idx]];
    await reorderMutation.mutateAsync(next.map((c) => c.id));
  };

  const setColor = async (col: LeadColumn, color: string) => {
    await updateMutation.mutateAsync({ id: col.id, data: { color } });
  };

  const toggleActive = async (col: LeadColumn) => {
    await updateMutation.mutateAsync({
      id: col.id,
      data: { is_active_stage: !col.is_active_stage },
    });
  };

  const togglePublic = async (col: LeadColumn) => {
    await updateMutation.mutateAsync({
      id: col.id,
      data: { is_public_visible: !col.is_public_visible },
    });
  };

  const confirmDelete = async () => {
    if (!deletingColumn) return;
    const needsMove = deletingColumn.lead_count > 0;
    if (needsMove && !moveTarget) return;
    await deleteMutation.mutateAsync({
      id: deletingColumn.id,
      moveTo: needsMove ? moveTarget : undefined,
    });
    setDeletingId(null);
    setMoveTarget('');
  };

  if (isLoading) {
    return <LoadingSpinner padding="24" />;
  }

  return (
    <nldd-container gap="12">
      <nldd-text size="xs" color="secondary">
        Eigenaren beheren hier de funnel-kolommen voor dit initiatief. Slug
        blijft vast na aanmaken zodat bestaande leads gekoppeld blijven.
        "Actieve fase" telt mee voor de overdue-filter; "Publiek zichtbaar"
        toont casuses op de publieke pagina.
      </nldd-text>

      <nldd-list appearance="box-tinted" dividers="always" accessible-label="Funnel-kolommen">
        {sortedColumns.map((col, idx) => (
          <ColumnRow
            key={col.id}
            col={col}
            isFirst={idx === 0}
            isLast={idx === sortedColumns.length - 1}
            reordering={reorderMutation.isPending}
            canDelete={sortedColumns.length > 1}
            editing={editing === col.id}
            editName={editName}
            onEditNameChange={setEditName}
            onStartEdit={() => startEdit(col)}
            onCommitEdit={commitEdit}
            onCancelEdit={() => setEditing(null)}
            onMoveUp={() => moveColumn(col, 'up')}
            onMoveDown={() => moveColumn(col, 'down')}
            onDelete={() => setDeletingId(col.id)}
            onToggleActive={() => toggleActive(col)}
            onTogglePublic={() => togglePublic(col)}
            onSetColor={(color) => setColor(col, color)}
          />
        ))}
      </nldd-list>

      {adding ? (
        <nldd-card background="tinted">
          <nldd-container gap="8" padding="12">
            {/* The listener sits on the element, not on a React onChange:
                nldd-text-field owns a shadow input and re-emits as a
                CustomEvent, which React does not map to onChange. Without
                this `draftName` stayed empty, so "Toevoegen" below was
                permanently disabled and a column could never be created. */}
            <nldd-text-field
              ref={draftNameRef}
              value={draftName}
              placeholder="Kolomnaam (bv. Strategisch)"
              accessible-label="Kolomnaam"
              autoFocus
            />
            <nldd-container layout="row" gap="8" vertical-alignment="center">
              <ColorSwatches selected={draftColor} onSelect={setDraftColor} />
              <nldd-container layout="row" gap="4" horizontal-alignment="right">
                <NlddButton
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setAdding(false);
                    setDraftName('');
                  }}
                  text="Annuleren"
                />
                <NlddButton
                  size="sm"
                  onClick={handleAdd}
                  loading={createMutation.isPending}
                  disabled={!draftName.trim()}
                  text="Toevoegen"
                />
              </nldd-container>
            </nldd-container>
          </nldd-container>
        </nldd-card>
      ) : (
        <NlddButton variant="secondary" size="sm" startIcon="plus" onClick={() => setAdding(true)} text="Kolom toevoegen" />
      )}

      <ConfirmDialog
        open={!!deletingColumn}
        onClose={() => {
          setDeletingId(null);
          setMoveTarget('');
        }}
        onConfirm={confirmDelete}
        title="Kolom verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={deleteMutation.isPending}
      >
        {deletingColumn && (
          <nldd-container gap="12">
            <nldd-text size="sm">
              Weet je zeker dat je <strong>{deletingColumn.name}</strong> wilt
              verwijderen?
            </nldd-text>
            {deletingColumn.lead_count > 0 ? (
              <nldd-container gap="4">
                <nldd-text size="sm" color="secondary">
                  Deze kolom bevat {deletingColumn.lead_count}{' '}
                  {deletingColumn.lead_count === 1 ? 'lead' : 'leads'}. Kies een
                  doel-kolom waar ze heen gaan:
                </nldd-text>
                <Select
                  value={moveTarget}
                  aria-label="Kolom om leads naartoe te verplaatsen"
                  onChange={(e) => setMoveTarget(e.target.value)}
                  placeholder="— Kies kolom —"
                  options={otherColumns.map((c) => ({ value: c.id, label: c.name }))}
                />
              </nldd-container>
            ) : (
              <nldd-text size="sm" color="secondary">
                De kolom is leeg en wordt direct verwijderd.
              </nldd-text>
            )}
          </nldd-container>
        )}
      </ConfirmDialog>
    </nldd-container>
  );
}

interface ColumnRowProps {
  col: LeadColumn;
  isFirst: boolean;
  isLast: boolean;
  reordering: boolean;
  canDelete: boolean;
  editing: boolean;
  editName: string;
  onEditNameChange: (value: string) => void;
  onStartEdit: () => void;
  onCommitEdit: () => void;
  onCancelEdit: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDelete: () => void;
  onToggleActive: () => void;
  onTogglePublic: () => void;
  onSetColor: (color: string) => void;
}

/**
 * One column row: a segmented `nldd-list-item` (rename control, reorder and
 * delete icon buttons) plus a second line of toggle chips. The chips stay
 * plain buttons rather than nldd-tag: they are two-state toggles the user
 * clicks to flip, not status labels, and nldd-tag has no click semantics.
 */
function ColumnRow({
  col,
  isFirst,
  isLast,
  reordering,
  canDelete,
  editing,
  editName,
  onEditNameChange,
  onStartEdit,
  onCommitEdit,
  onCancelEdit,
  onMoveUp,
  onMoveDown,
  onDelete,
  onToggleActive,
  onTogglePublic,
  onSetColor,
}: ColumnRowProps) {
  const nameFieldRef = useRef<HTMLElement>(null);
  const renameTriggerRef = useRef<HTMLElement>(null);
  const [pickingColor, setPickingColor] = useState(false);

  useNlddEvent(nameFieldRef, 'input', (e) => onEditNameChange(eventValue(e)));
  useNlddEvent(
    nameFieldRef,
    'blur',
    useCallback(() => onCommitEdit(), [onCommitEdit]),
  );
  useNlddEvent(renameTriggerRef, 'click', onStartEdit);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') onCommitEdit();
    if (e.key === 'Escape') onCancelEdit();
  };

  return (
    <nldd-list-item>
      <nldd-container gap="8" padding-block="4" width="full">
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <nldd-container layout="row" gap="8" vertical-alignment="center" width="full">
            <nldd-tag text={col.slug} color={leadColumnTagColor(col.color)} size="sm" />
            {editing ? (
              <nldd-text-field
                ref={nameFieldRef}
                value={editName}
                onKeyDown={handleKeyDown}
                autoFocus
                accessible-label="Kolomnaam"
                style={{ flex: 1 }}
              />
            ) : (
              <nldd-list-item-segment ref={renameTriggerRef} button accessible-label={`${col.name} hernoemen`}>
                {col.name}
              </nldd-list-item-segment>
            )}
            <nldd-text size="xs" color="secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {col.lead_count} {col.lead_count === 1 ? 'lead' : 'leads'}
            </nldd-text>
          </nldd-container>

          <div className="hug">
            <NlddIconButton
              icon="chevron-up"
              accessibleLabel="Omhoog"
              variant="neutral-transparent"
              size="sm"
              disabled={isFirst || reordering}
              onClick={onMoveUp}
            />
            <NlddIconButton
              icon="chevron-down"
              accessibleLabel="Omlaag"
              variant="neutral-transparent"
              size="sm"
              disabled={isLast || reordering}
              onClick={onMoveDown}
            />
            <NlddIconButton
              icon="trash"
              accessibleLabel={canDelete ? 'Verwijderen' : 'Laatste kolom kan niet weg'}
              variant="neutral-transparent"
              size="sm"
              disabled={!canDelete}
              onClick={onDelete}
            />
          </div>
        </nldd-container>

        <nldd-container layout="wrap" gap="12" padding-left="4">
          <ToggleChip
            active={col.is_active_stage}
            activeIcon="check-mark"
            inactiveIcon="close"
            label="Actieve fase"
            title="Telt mee voor overdue/stale-filter"
            activeColor="success"
            onToggle={onToggleActive}
          />
          <ToggleChip
            active={col.is_public_visible}
            activeIcon="eye"
            inactiveIcon="eye-slash"
            label="Publiek zichtbaar"
            title="Toont casuses op publieke pagina"
            activeColor="lintblauw"
            onToggle={onTogglePublic}
          />
          <CurrentColorButton
            color={col.color}
            expanded={pickingColor}
            onToggle={() => setPickingColor((v) => !v)}
          />
        </nldd-container>

        {/* The palette only for the row being recolored: shown on every row,
            it took a full line each and made seven columns a long scroll. */}
        {pickingColor && (
          <nldd-container padding-left="4">
            <ColorSwatches
              selected={col.color}
              onSelect={(color) => {
                onSetColor(color);
                setPickingColor(false);
              }}
            />
          </nldd-container>
        )}
      </nldd-container>
    </nldd-list-item>
  );
}

interface ToggleChipProps {
  active: boolean;
  activeIcon: string;
  inactiveIcon: string;
  label: string;
  title: string;
  /** nldd-tag color to show while active; inactive always reads neutral. */
  activeColor: NlddTagColor;
  onToggle: () => void;
}

/**
 * A two-state toggle the user clicks to flip, not a status label, so it
 * stays a clickable segment rather than nldd-tag (which has no click
 * semantics) — the color still comes from the same closed set nldd-tag uses,
 * carried via a CSS custom property since nldd-list-item-segment has no
 * `color` attribute of its own.
 */
function ToggleChip({ active, activeIcon, inactiveIcon, label, title, activeColor, onToggle }: ToggleChipProps) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', onToggle);

  return (
    <nldd-list-item-segment ref={ref} button title={title}>
      <nldd-tag text={label} icon={active ? activeIcon : inactiveIcon} color={active ? activeColor : 'neutral'} size="sm" />
    </nldd-list-item-segment>
  );
}

function swatchIconColor(color: NlddTagColor): NlddIconColor {
  return color === 'neutral' ? 'secondary-content' : (color as NlddIconColor);
}

/** A filled circle in the color: the swatch in both controls below. */
function Swatch({ color }: { color: NlddTagColor }) {
  return <nldd-icon slot="icon" icon="circle-filled" color={swatchIconColor(color)} />;
}

/** The column's color as one swatch; pressing it opens the palette. */
function CurrentColorButton({
  color,
  expanded,
  onToggle,
}: {
  color: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', onToggle);
  const preset = COLOR_PRESETS.find((p) => p.value === color) ?? COLOR_PRESETS[0];
  return (
    <nldd-icon-button
      ref={ref}
      appearance="neutral-transparent"
      size="xs"
      accessible-label={`Kleur wijzigen, nu ${preset.label}`}
      expanded={orUndef(expanded)}
    >
      <Swatch color={preset.value} />
    </nldd-icon-button>
  );
}

/**
 * The palette as a radio group: one toggle button per color, the chosen one
 * drawn selected by the button itself, so the choice does not rest on the
 * color alone, and each option is announced by its name.
 */
function ColorSwatches({
  selected,
  onSelect,
}: {
  selected: string;
  onSelect: (color: NlddTagColor) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(
    ref,
    'change',
    useCallback(
      (event: Event) => {
        const value = (event as CustomEvent<{ value?: string }>).detail?.value;
        if (value) onSelect(value as NlddTagColor);
      },
      [onSelect],
    ),
  );

  return (
    <nldd-toggle-button-group ref={ref} type="radio" size="xs" accessible-label="Kolomkleur">
      {COLOR_PRESETS.map((preset) => (
        <nldd-toggle-button
          key={preset.value}
          variant="icon"
          value={preset.value}
          accessible-label={preset.label}
          selected={orUndef(selected === preset.value)}
        >
          <Swatch color={preset.value} />
        </nldd-toggle-button>
      ))}
    </nldd-toggle-button-group>
  );
}
