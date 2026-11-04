import { useCallback, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useSamenwerkingsverbanden,
  useCreateSamenwerkingsverband,
} from '@/hooks/useSamenwerkingsverbanden';
import { Badge } from '@/components/common/Badge';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { Input } from '@/components/common/Input';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { Icon } from '@/components/nldd/Icon';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import {
  SAMENWERKINGSVERBAND_TYPE_LABELS,
  SAMENWERKINGSVERBAND_TYPE_BADGE_COLORS,
  SAMENWERKINGSVERBAND_TYPE_OPTIONS,
  type Samenwerkingsverband,
  type SamenwerkingsverbandCreate,
} from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

const ALL_TYPE_OPTIONS: SelectOption[] = [
  { value: '', label: 'Alle types' },
  ...SAMENWERKINGSVERBAND_TYPE_OPTIONS,
];

/** True when the click asked for something other than plain navigation. */
function isModifiedClick(event: MouseEvent): boolean {
  return event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button === 1;
}

interface SamenwerkingsverbandCardProps {
  swv: Samenwerkingsverband;
}

/**
 * `nldd-card href` renders a real `<a>`, which is what we want for
 * middle-click/cmd-click, but a plain click still needs to go through
 * react-router rather than a full page load — same pattern as
 * `NlddListItemLink` in components/nldd/NlddLink.tsx.
 */
function SamenwerkingsverbandCard({ swv }: SamenwerkingsverbandCardProps) {
  const ref = useRef<HTMLElement>(null);
  const navigate = useNavigate();
  const to = `/samenwerkingsverbanden/${swv.id}`;

  const onClick = useCallback(
    (event: Event) => {
      const mouse = event as MouseEvent;
      if (isModifiedClick(mouse)) return;
      event.preventDefault();
      navigate(to);
    },
    [navigate, to],
  );
  useNlddEvent(ref, 'click', onClick);

  return (
    <nldd-card ref={ref} href={to} accessible-label={swv.naam}>
      <nldd-container gap="8" padding="16">
        <nldd-container layout="row" width="full" gap="8" horizontal-alignment="right" vertical-alignment="center">
          <Badge color={SAMENWERKINGSVERBAND_TYPE_BADGE_COLORS[swv.type] ?? 'coolgray'}>
            {SAMENWERKINGSVERBAND_TYPE_LABELS[swv.type] ?? swv.type}
          </Badge>
          <nldd-container layout="row" gap="4" vertical-alignment="center">
            <Icon name="users" size="xs" />
            <nldd-text size="xs" color="secondary">{swv.aantal_leden}</nldd-text>
          </nldd-container>
        </nldd-container>
        <nldd-text size="sm" weight="bold">{swv.naam}</nldd-text>
        {swv.eind_datum && (
          <nldd-text size="xs" color="secondary">
            Eindigt {new Date(swv.eind_datum).toLocaleDateString('nl-NL')}
          </nldd-text>
        )}
      </nldd-container>
    </nldd-card>
  );
}

/** Reads `checked` off an nldd-checkbox-field's `change` detail. */
function checkedValue(event: Event): boolean {
  return Boolean((event as CustomEvent<{ checked?: boolean }>).detail?.checked);
}

function ActiefOnlyCheckbox({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', useCallback((e: Event) => onChange(checkedValue(e)), [onChange]));
  return <nldd-checkbox-field ref={ref} label="Alleen actieve" checked={orUndef(checked)} />;
}

export function SamenwerkingsverbandenPage() {
  const [typeFilter, setTypeFilter] = useState('');
  const [actiefOnly, setActiefOnly] = useState(true);
  const [search, setSearch] = useState('');
  const { data = [], isLoading } = useSamenwerkingsverbanden({
    type: typeFilter || undefined,
    actief: actiefOnly ? true : undefined,
    search: search || undefined,
  });
  const createMutation = useCreateSamenwerkingsverband();

  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<SamenwerkingsverbandCreate>({
    naam: '',
    type: 'programma',
  });

  const resetForm = () => {
    setForm({ naam: '', type: 'programma' });
    setError(null);
    setShowForm(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await createMutation.mutateAsync(form);
      resetForm();
    } catch {
      setError('Fout bij aanmaken samenwerkingsverband.');
    }
  };

  return (
    <nldd-container gap="24">
      <nldd-toolbar accessible-label="Samenwerkingsverbandacties">
        {/* `min-width` makes the item fluid, per its own docs, and that is what
            gives the wrap row below a width to break against. Without it the
            item measures its content, the row measures the item, and both end
            at zero: filters that take up space and show nothing. */}
        <nldd-toolbar-item slot="start" priority={1} min-width="464px">
          <nldd-container layout="wrap" gap="12" vertical-alignment="bottom">
            <nldd-container width="256px">
              <Input
                label="Zoeken"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Naam..."
              />
            </nldd-container>
            <nldd-container width="192px">
              <CreatableSelect
                label="Type"
                value={typeFilter}
                onChange={setTypeFilter}
                options={ALL_TYPE_OPTIONS}
                searchable={false}
              />
            </nldd-container>
            <ActiefOnlyCheckbox checked={actiefOnly} onChange={setActiefOnly} />
          </nldd-container>
        </nldd-toolbar-item>
        <nldd-toolbar-item slot="end">
          <NlddButton
            variant="primary"
            startIcon="plus"
            onClick={() => { resetForm(); setShowForm(true); }}
            text="Nieuw samenwerkingsverband"
            compactBelowSm
          />
          <nldd-menu-item slot="overflow" text="Nieuw samenwerkingsverband" icon="plus"></nldd-menu-item>
        </nldd-toolbar-item>
      </nldd-toolbar>

      {showForm && (
        <nldd-card>
          <nldd-container gap="16" padding="24">
            <nldd-container layout="row" gap="8" vertical-alignment="center">
              <nldd-title size={4}><h3>Nieuw samenwerkingsverband</h3></nldd-title>
              <nldd-spacer size="flexible" direction="horizontal" />
              <NlddIconButton
                icon="close"
                accessibleLabel="Sluiten"
                variant="neutral-transparent"
                size="sm"
                onClick={resetForm}
              />
            </nldd-container>
            <nldd-form>
            <form onSubmit={handleSubmit}>
              <nldd-container gap="16">
                <nldd-container layout="grid" column-count={1} sm-column-count={2} gap="16">
                  <Input
                    label="Naam"
                    value={form.naam}
                    onChange={(e) => setForm((f) => ({ ...f, naam: e.target.value }))}
                    autoComplete="organization"
                    required
                    autoFocus
                  />
                  <CreatableSelect
                    label="Type"
                    value={form.type}
                    onChange={(v) => setForm((f) => ({ ...f, type: v }))}
                    options={SAMENWERKINGSVERBAND_TYPE_OPTIONS}
                    searchable={false}
                  />
                  <Input
                    label="Startdatum"
                    type="date"
                    value={form.start_datum ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, start_datum: e.target.value || null }))}
                  />
                  <Input
                    label="Einddatum"
                    type="date"
                    value={form.eind_datum ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, eind_datum: e.target.value || null }))}
                  />
                </nldd-container>
                <RichTextFormField
                  label="Beschrijving"
                  value={form.beschrijving ?? ''}
                  onChange={(v) => setForm((f) => ({ ...f, beschrijving: v }))}
                  rows={3}
                />
                {error && <nldd-text size="sm" color="critical">{error}</nldd-text>}
                <nldd-container layout="row" gap="8" horizontal-alignment="right">
                  <NlddButton variant="secondary" onClick={resetForm} type="button" text="Annuleren" />
                  <NlddButton type="submit" loading={createMutation.isPending} text="Aanmaken" />
                </nldd-container>
              </nldd-container>
            </form>
            </nldd-form>
          </nldd-container>
        </nldd-card>
      )}

      {isLoading ? (
        <nldd-container layout="row" horizontal-alignment="center" padding="48"><LoadingSpinner /></nldd-container>
      ) : data.length === 0 ? (
        <nldd-container padding="48" horizontal-alignment="center">
          <nldd-text size="sm" color="secondary" horizontal-alignment="center">
            Geen samenwerkingsverbanden gevonden.
          </nldd-text>
        </nldd-container>
      ) : (
        <nldd-collection layout="grid" item-min-width="280px" gap="12">
          {data.map((swv) => (
            <SamenwerkingsverbandCard key={swv.id} swv={swv} />
          ))}
        </nldd-collection>
      )}
    </nldd-container>
  );
}
