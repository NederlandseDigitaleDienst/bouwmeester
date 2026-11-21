import { useState, useMemo, useRef } from 'react';
import { useSharing, useCreateSharing, useDeleteSharing } from '@/hooks/useSharing';
import { useOrganisatieFlat } from '@/hooks/useOrganisatie';
import { usePermissions } from '@/hooks/usePermissions';
import type { SharingGrantCreate } from '@/hooks/useSharing';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Select } from '@/components/common/Select';

type ShareMode = 'eenheid' | 'node';

const ACCESS_LABELS: Record<string, string> = {
  read: 'Lezen',
  edit: 'Bewerken',
};

const ACCESS_OPTIONS = Object.entries(ACCESS_LABELS).map(([value, label]) => ({ value, label }));

const INITIAL_FORM: SharingGrantCreate & { mode: ShareMode } = {
  mode: 'eenheid',
  source_eenheid_id: undefined,
  source_node_id: undefined,
  target_eenheid_id: '',
  access_level: 'read',
  reason: '',
  geldig_van: '',
  geldig_tot: '',
};

export function SharingManager() {
  const { data: shares, isLoading } = useSharing();
  const { data: eenheden } = useOrganisatieFlat();
  const { managesEenheid } = usePermissions();
  const createSharing = useCreateSharing();
  const deleteSharing = useDeleteSharing();

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(INITIAL_FORM);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const modeGroupRef = useRef<HTMLElement>(null);
  const sourceNodeRef = useRef<HTMLElement>(null);
  const reasonRef = useRef<HTMLElement>(null);
  const geldigVanRef = useRef<HTMLElement>(null);
  const geldigTotRef = useRef<HTMLElement>(null);

  useNlddEvent(modeGroupRef, 'change', (e) => {
    const mode = eventValue(e) as ShareMode;
    if (mode === 'eenheid') setForm((f) => ({ ...f, mode, source_node_id: undefined }));
    else if (mode === 'node') setForm((f) => ({ ...f, mode, source_eenheid_id: undefined }));
  });
  useNlddEvent(sourceNodeRef, 'input', (e) =>
    setForm((f) => ({ ...f, source_node_id: eventValue(e) || undefined })),
  );
  useNlddEvent(reasonRef, 'input', (e) => setForm((f) => ({ ...f, reason: eventValue(e) })));
  useNlddEvent(geldigVanRef, 'input', (e) => setForm((f) => ({ ...f, geldig_van: eventValue(e) })));
  useNlddEvent(geldigTotRef, 'input', (e) => setForm((f) => ({ ...f, geldig_tot: eventValue(e) })));

  const sortedEenheden = useMemo(
    () => [...(eenheden ?? [])].sort((a, b) => a.naam.localeCompare(b.naam)),
    [eenheden],
  );
  // Sharing needs org:manage on the source: only eenheden this person manages.
  const sourceEenheden = useMemo(
    () => sortedEenheden.filter((e) => managesEenheid(e.id)),
    [sortedEenheden, managesEenheid],
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const payload: SharingGrantCreate = {
      target_eenheid_id: form.target_eenheid_id,
      access_level: form.access_level,
    };

    if (form.mode === 'eenheid') {
      payload.source_eenheid_id = form.source_eenheid_id;
    } else {
      payload.source_node_id = form.source_node_id;
    }

    if (form.reason?.trim()) payload.reason = form.reason.trim();
    if (form.geldig_van) payload.geldig_van = form.geldig_van;
    if (form.geldig_tot) payload.geldig_tot = form.geldig_tot;

    createSharing.mutate(payload, {
      onSuccess: () => {
        setForm(INITIAL_FORM);
        setShowForm(false);
      },
    });
  };

  const handleDelete = (id: string) => {
    deleteSharing.mutate(id, {
      onSuccess: () => setConfirmDeleteId(null),
    });
  };

  if (isLoading) {
    return <LoadingSpinner padding="32" />;
  }

  return (
    <nldd-container gap="16">
      {/* Toggle add form */}
      {!showForm && (
        <NlddButton
          text="Nieuwe deling"
          startIcon="plus"
          onClick={() => setShowForm(true)}
        />
      )}

      {/* Add form */}
      {showForm && (
        <nldd-card>
        <nldd-form>
        <form onSubmit={handleSubmit}>
          <nldd-container padding="16" gap="12">
          <nldd-title size="display-4"><h3>Nieuwe deling aanmaken</h3></nldd-title>

          {/* Mode toggle */}
          <nldd-radio-button-group ref={modeGroupRef} accessible-label="Type deling" name="share-mode">
            <nldd-radio-button-field
              label="Hele eenheid delen"
              value="eenheid"
              checked={form.mode === 'eenheid' ? true : undefined}
            />
            <nldd-radio-button-field
              label="Specifiek item delen"
              value="node"
              checked={form.mode === 'node' ? true : undefined}
            />
          </nldd-radio-button-group>

          {/* Source */}
          {form.mode === 'eenheid' ? (
            <Select
              label="Broneenheid"
              value={form.source_eenheid_id ?? ''}
              onChange={(e) =>
                setForm((f) => ({ ...f, source_eenheid_id: e.target.value || undefined }))
              }
              placeholder="Selecteer eenheid..."
              options={sourceEenheden.map((e) => ({ value: e.id, label: e.naam }))}
              required
            />
          ) : (
            <nldd-form-field label="Item ID (corpus node)">
              <nldd-text-field
                ref={sourceNodeRef}
                value={form.source_node_id ?? ''}
                placeholder="UUID van het item..."
                required
              />
            </nldd-form-field>
          )}

          {/* Target */}
          <Select
            label="Doeleenheid"
            value={form.target_eenheid_id}
            onChange={(e) => setForm((f) => ({ ...f, target_eenheid_id: e.target.value }))}
            placeholder="Selecteer eenheid..."
            options={sortedEenheden.map((e) => ({ value: e.id, label: e.naam }))}
            required
          />

          {/* Access level. Always has a value, so marked required rather than
              letting Select label it optional. */}
          <Select
            label="Toegangsniveau"
            value={form.access_level}
            onChange={(e) =>
              setForm((f) => ({ ...f, access_level: e.target.value as 'read' | 'edit' }))
            }
            options={ACCESS_OPTIONS}
            required
          />

          {/* Reason */}
          <nldd-form-field label="Reden" optional>
            <nldd-text-field
              ref={reasonRef}
              value={form.reason ?? ''}
              placeholder="Bijv. samenwerking project X"
            />
          </nldd-form-field>

          {/* Date range */}
          <nldd-container layout="grid" column-count={2} gap="12">
            <nldd-form-field label="Geldig van" optional>
              <nldd-date-field ref={geldigVanRef} value={form.geldig_van ?? ''} />
            </nldd-form-field>
            <nldd-form-field label="Geldig tot" optional>
              <nldd-date-field ref={geldigTotRef} value={form.geldig_tot ?? ''} />
            </nldd-form-field>
          </nldd-container>

          {/* Form actions */}
          <nldd-container layout="row" gap="8">
            <NlddButton
              type="submit"
              text="Toevoegen"
              startIcon="plus"
              disabled={createSharing.isPending}
            />
            <NlddButton
              type="button"
              text="Annuleren"
              variant="neutral-tinted"
              onClick={() => {
                setForm(INITIAL_FORM);
                setShowForm(false);
              }}
            />
          </nldd-container>
          </nldd-container>
        </form>
        </nldd-form>
        </nldd-card>
      )}

      {/* Shares table */}
      <nldd-table
        columns="minmax(160px,1fr) minmax(160px,1fr) 120px minmax(160px,1fr) 120px 120px 48px"
        sm-columns="1fr 1fr 48px"
        md-columns="1fr 1fr 120px 48px"
        accessible-label="Actieve delingen"
      >
        <nldd-table-row slot="header">
          <nldd-text-cell text="Bron" />
          <nldd-text-cell text="Doel" />
          <nldd-text-cell text="Niveau" hide-below="md" />
          <nldd-text-cell text="Reden" hide-below="lg" />
          <nldd-text-cell text="Geldig van" hide-below="lg" />
          <nldd-text-cell text="Geldig tot" hide-below="lg" />
          <nldd-text-cell />
        </nldd-table-row>
        {shares?.map((share) => (
          <nldd-table-row key={share.id}>
            <nldd-text-cell text={share.source_eenheid_naam ?? 'Specifiek item'} />
            <nldd-text-cell text={share.target_eenheid_naam ?? share.target_eenheid_id} />
            <nldd-text-cell
              text={ACCESS_LABELS[share.access_level] ?? share.access_level}
              color="secondary"
              hide-below="md"
            />
            <nldd-text-cell text={share.reason || '-'} color="secondary" hide-below="lg" />
            <nldd-text-cell
              text={new Date(share.geldig_van).toLocaleDateString('nl-NL')}
              color="secondary"
              hide-below="lg"
            />
            <nldd-text-cell
              text={share.geldig_tot ? new Date(share.geldig_tot).toLocaleDateString('nl-NL') : '-'}
              color="secondary"
              hide-below="lg"
            />
            <nldd-cell>
              {confirmDeleteId === share.id ? (
                <nldd-container layout="row" gap="4" vertical-alignment="center">
                  <NlddButton
                    text="Ja"
                    variant="destructive"
                    size="xs"
                    disabled={deleteSharing.isPending}
                    onClick={() => handleDelete(share.id)}
                  />
                  <NlddButton
                    text="Nee"
                    variant="neutral-tinted"
                    size="xs"
                    onClick={() => setConfirmDeleteId(null)}
                  />
                </nldd-container>
              ) : (
                <NlddIconButton
                  icon="trash"
                  accessibleLabel="Verwijderen"
                  variant="neutral-transparent"
                  size="sm"
                  onClick={() => setConfirmDeleteId(share.id)}
                />
              )}
            </nldd-cell>
          </nldd-table-row>
        ))}
        <div slot="empty">
          <EmptyState icon="inbox" title="Geen actieve delingen" />
        </div>
      </nldd-table>

      <nldd-text size="xs" color="secondary">
        <p>
          Delingen geven een organisatie-eenheid toegang tot gegevens van een andere eenheid of een
          specifiek item. Verwijder een deling om de toegang in te trekken.
        </p>
      </nldd-text>
    </nldd-container>
  );
}
