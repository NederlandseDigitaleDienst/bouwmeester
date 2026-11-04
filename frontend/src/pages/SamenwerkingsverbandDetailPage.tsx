import { useCallback, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  useSamenwerkingsverband,
  useUpdateSamenwerkingsverband,
  useDeleteSamenwerkingsverband,
  useAddLid,
  useUpdateLid,
  useRemoveLid,
} from '@/hooks/useSamenwerkingsverbanden';
import { usePeople } from '@/hooks/usePeople';
import { Badge } from '@/components/common/Badge';
import { Input } from '@/components/common/Input';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { PersonQuickCreateForm } from '@/components/people/PersonQuickCreateForm';
import { Icon } from '@/components/nldd/Icon';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { useNlddEvent } from '@/components/nldd/events';
import { formatDate } from '@/utils/dates';
import {
  SAMENWERKINGSVERBAND_TYPE_LABELS,
  SAMENWERKINGSVERBAND_TYPE_BADGE_COLORS,
  SAMENWERKINGSVERBAND_TYPE_OPTIONS,
  type SamenwerkingsverbandLid,
  type SamenwerkingsverbandLidUpdate,
  type SamenwerkingsverbandUpdate,
} from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

/** True when the click asked for something other than plain navigation. */
function isModifiedClick(event: MouseEvent): boolean {
  return event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button === 1;
}

/** `nldd-link` that navigates through the router instead of a full page load. */
function BackLink({ to, text }: { to: string; text: string }) {
  const ref = useRef<HTMLElement>(null);
  const navigate = useNavigate();
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
  return <nldd-link ref={ref} href={to} size="sm" start-icon="arrow-left" text={text} />;
}

export function SamenwerkingsverbandDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: swv, isLoading } = useSamenwerkingsverband(id ?? null);
  const updateMutation = useUpdateSamenwerkingsverband();
  const deleteMutation = useDeleteSamenwerkingsverband();
  const addLidMutation = useAddLid();
  const updateLidMutation = useUpdateLid();
  const removeLidMutation = useRemoveLid();
  const { data: people = [] } = usePeople();

  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<SamenwerkingsverbandUpdate>({});
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmRemoveLidId, setConfirmRemoveLidId] = useState<string | null>(null);

  // Lid-toevoeg-form
  const [showAddLid, setShowAddLid] = useState(false);
  const [newLidPersonId, setNewLidPersonId] = useState('');
  const [newLidRol, setNewLidRol] = useState('');

  // Inline persoon-aanmaken vanuit lid-toevoeg-flow
  const [showPersonCreate, setShowPersonCreate] = useState(false);
  const [personCreateName, setPersonCreateName] = useState('');

  // Lid-bewerken-form (één lid tegelijk)
  const [editingLidId, setEditingLidId] = useState<string | null>(null);
  const [lidEditForm, setLidEditForm] = useState<{
    rol: string;
    start_datum: string;
    eind_datum: string;
  }>({ rol: '', start_datum: '', eind_datum: '' });

  if (isLoading) {
    return <nldd-container layout="row" horizontal-alignment="center" padding="48"><LoadingSpinner /></nldd-container>;
  }
  if (!swv || !id) {
    return (
      <nldd-container padding="48" max-width="672px" horizontal-alignment="center">
        <nldd-text size="sm" color="secondary" horizontal-alignment="center">
          Samenwerkingsverband niet gevonden.
        </nldd-text>
      </nldd-container>
    );
  }

  const startEdit = () => {
    setEditForm({
      naam: swv.naam,
      type: swv.type,
      beschrijving: swv.beschrijving ?? '',
      start_datum: swv.start_datum ?? null,
      eind_datum: swv.eind_datum ?? null,
    });
    setEditing(true);
  };

  const handleSaveEdit = async () => {
    if (!id) return;
    try {
      await updateMutation.mutateAsync({ id, data: editForm });
      setEditing(false);
    } catch {
      // toast wordt al getoond
    }
  };

  const handleDelete = async () => {
    if (!id) return;
    try {
      await deleteMutation.mutateAsync(id);
      navigate('/samenwerkingsverbanden');
    } catch {
      setConfirmDelete(false);
    }
  };

  const handleAddLid = async () => {
    if (!id || !newLidPersonId) return;
    try {
      await addLidMutation.mutateAsync({
        swvId: id,
        data: {
          person_id: newLidPersonId,
          rol: newLidRol || null,
          start_datum: new Date().toISOString().slice(0, 10),
        },
      });
      setShowAddLid(false);
      setNewLidPersonId('');
      setNewLidRol('');
    } catch {
      // toast
    }
  };

  const handleRemoveLid = async () => {
    if (!id || !confirmRemoveLidId) return;
    try {
      await removeLidMutation.mutateAsync({ swvId: id, lidId: confirmRemoveLidId });
      setConfirmRemoveLidId(null);
    } catch {
      setConfirmRemoveLidId(null);
    }
  };

  const handleCreatePerson = async (text: string): Promise<string | null> => {
    setPersonCreateName(text);
    setShowPersonCreate(true);
    return null;
  };

  const handlePersonCreated = (personId: string) => {
    setNewLidPersonId(personId);
  };

  const startEditLid = (lid: SamenwerkingsverbandLid) => {
    setEditingLidId(lid.id);
    setLidEditForm({
      rol: lid.rol ?? '',
      start_datum: lid.start_datum ?? '',
      eind_datum: lid.eind_datum ?? '',
    });
  };

  const cancelEditLid = () => {
    setEditingLidId(null);
  };

  const handleSaveLid = async () => {
    if (!id || !editingLidId) return;
    const data: SamenwerkingsverbandLidUpdate = {
      rol: lidEditForm.rol.trim() || null,
      eind_datum: lidEditForm.eind_datum || null,
    };
    // Lege start_datum niet meesturen: kolom is NOT NULL en er is geen
    // semantische "lid sinds onbekend"-state. Veld blijft dan onveranderd.
    if (lidEditForm.start_datum) {
      data.start_datum = lidEditForm.start_datum;
    }
    try {
      await updateLidMutation.mutateAsync({ swvId: id, lidId: editingLidId, data });
      setEditingLidId(null);
    } catch {
      // toast
    }
  };

  const peopleAlIngedeeld = new Set(swv.leden.map((l) => l.person_id));
  const personOptions: SelectOption[] = people
    .filter((p) => p.is_active && !p.is_agent && !peopleAlIngedeeld.has(p.id))
    .sort((a, b) => a.naam.localeCompare(b.naam))
    .map((p) => ({
      value: p.id,
      label: p.naam,
      description: p.functie ?? undefined,
    }));

  const periode =
    swv.start_datum && swv.eind_datum
      ? `${formatDate(swv.start_datum)} – ${formatDate(swv.eind_datum)}`
      : swv.start_datum
        ? `sinds ${formatDate(swv.start_datum)}`
        : swv.eind_datum
          ? `tot ${formatDate(swv.eind_datum)}`
          : null;

  return (
    <nldd-container gap="24" max-width="896px">
      {/* `wrap`: on a phone the link and both buttons do not fit on one
          line. As a row, the link gave way and broke over two lines; now the
          buttons move to the next line and every label stays whole. */}
      <nldd-container layout="wrap" width="full" gap="8" vertical-alignment="center">
        <div className="hug">
          <BackLink to="/samenwerkingsverbanden" text="Terug naar overzicht" />
        </div>
        {!editing && (
          <>
          <nldd-spacer direction="horizontal" size="flexible" />
          <div className="hug">
            <NlddButton variant="neutral-transparent" size="sm" startIcon="pencil" onClick={startEdit} text="Bewerken" />
            <NlddButton
              variant="neutral-transparent"
              size="sm"
              startIcon="trash"
              onClick={() => setConfirmDelete(true)}
              text="Verwijderen"
            />
          </div>
          </>
        )}
      </nldd-container>

      <nldd-card>
        <nldd-container padding="24">
          {editing ? (
            <nldd-container gap="16">
              <nldd-container layout="grid" column-count={1} sm-column-count={2} gap="16">
                <Input
                  label="Naam"
                  value={editForm.naam ?? ''}
                  onChange={(e) => setEditForm((f) => ({ ...f, naam: e.target.value }))}
                  autoComplete="organization"
                  required
                />
                <CreatableSelect
                  label="Type"
                  value={editForm.type ?? swv.type}
                  onChange={(v) => setEditForm((f) => ({ ...f, type: v }))}
                  options={SAMENWERKINGSVERBAND_TYPE_OPTIONS}
                  searchable={false}
                />
                <Input
                  label="Startdatum"
                  type="date"
                  value={editForm.start_datum ?? ''}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, start_datum: e.target.value || null }))
                  }
                />
                <Input
                  label="Einddatum"
                  type="date"
                  value={editForm.eind_datum ?? ''}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, eind_datum: e.target.value || null }))
                  }
                />
              </nldd-container>
              <RichTextFormField
                label="Beschrijving"
                value={editForm.beschrijving ?? ''}
                onChange={(v) => setEditForm((f) => ({ ...f, beschrijving: v }))}
                rows={4}
              />
              <nldd-container layout="row" gap="8" horizontal-alignment="right">
                <NlddButton variant="secondary" onClick={() => setEditing(false)} text="Annuleren" />
                <NlddButton onClick={handleSaveEdit} loading={updateMutation.isPending} text="Opslaan" />
              </nldd-container>
            </nldd-container>
          ) : (
            <nldd-container gap="12">
              {/* The dates are part of the meta line under the title. As a
                  column beside the title they were squeezed on a phone until
                  "1-5-2022" broke into "1-5-" and "2022". */}
              <nldd-container gap="4">
                {/* h2: the app header's title bar already renders this
                    route's h1 ("Samenwerkingsverbanden"). */}
                <nldd-title size={3}><h2>{swv.naam}</h2></nldd-title>
                <nldd-container layout="wrap" gap="8" vertical-alignment="center">
                  <Badge color={SAMENWERKINGSVERBAND_TYPE_BADGE_COLORS[swv.type] ?? 'coolgray'}>
                    {SAMENWERKINGSVERBAND_TYPE_LABELS[swv.type] ?? swv.type}
                  </Badge>
                  <div className="hug">
                    <Icon name="users" size="xs" />
                    <nldd-text size="xs" color="secondary">
                      {swv.aantal_leden} {swv.aantal_leden === 1 ? 'lid' : 'leden'}
                    </nldd-text>
                  </div>
                  {periode && (
                    <div className="hug">
                      <Icon name="calendar" size="xs" />
                      <nldd-text size="xs" color="secondary">{periode}</nldd-text>
                    </div>
                  )}
                </nldd-container>
              </nldd-container>
              {swv.beschrijving && (
                <nldd-container padding-top="8">
                  <RichTextDisplay content={swv.beschrijving} />
                </nldd-container>
              )}
            </nldd-container>
          )}
        </nldd-container>
      </nldd-card>

      <nldd-card>
        <nldd-container gap="12" padding="24">
          <nldd-container layout="row" width="full" gap="8" vertical-alignment="center">
            {/* The heading fills the row, so it starts on the left and the
                button ends on the right. With only right-alignment both
                were pushed right. */}
            <nldd-container width="fit-content" className="row-fill">
              <nldd-title size={4}><h2>Leden</h2></nldd-title>
            </nldd-container>
            <NlddButton variant="neutral-transparent" size="sm" startIcon="plus" onClick={() => setShowAddLid(true)} text="Toevoegen" />
          </nldd-container>

          {showAddLid && (
            // `base`: an outline on the card's own surface, as the hand-drawn
            // border was; the tinted default would fill it in.
            <nldd-box background="base">
            <nldd-container gap="12" padding="12">
              <nldd-container layout="grid" column-count={1} sm-column-count={2} gap="12">
                <CreatableSelect
                  label="Persoon"
                  value={newLidPersonId}
                  onChange={setNewLidPersonId}
                  options={personOptions}
                  placeholder="Zoek persoon..."
                  onCreate={handleCreatePerson}
                  createLabel="Nieuwe persoon aanmaken"
                />
                <Input
                  label="Rol (optioneel)"
                  value={newLidRol}
                  onChange={(e) => setNewLidRol(e.target.value)}
                  placeholder="bv. trekker, voorzitter"
                />
              </nldd-container>
              <nldd-container layout="row" gap="8" horizontal-alignment="right">
                <NlddButton
                  variant="secondary"
                  size="sm"
                  onClick={() => { setShowAddLid(false); setNewLidPersonId(''); setNewLidRol(''); }}
                  text="Annuleren"
                />
                <NlddButton
                  size="sm"
                  onClick={handleAddLid}
                  loading={addLidMutation.isPending}
                  disabled={!newLidPersonId}
                  text="Toevoegen"
                />
              </nldd-container>
            </nldd-container>
            </nldd-box>
          )}

        {swv.leden.length === 0 ? (
          <nldd-inline-dialog text="Nog geen leden." />
        ) : (
          <nldd-list type="list" appearance="box-tinted">
            {swv.leden.map((lid) => {
              const isEditing = editingLidId === lid.id;
              if (isEditing) {
                return (
                  <nldd-list-item key={lid.id}>
                    <nldd-container gap="12" width="full" padding-block="8">
                      <nldd-text size="sm" weight="medium">{lid.person_naam}</nldd-text>
                      <nldd-container layout="grid" column-count={1} sm-column-count={3} gap="12">
                        <Input
                          label="Rol"
                          value={lidEditForm.rol}
                          onChange={(e) =>
                            setLidEditForm((f) => ({ ...f, rol: e.target.value }))
                          }
                          placeholder="bv. trekker, voorzitter"
                        />
                        <Input
                          label="Startdatum"
                          type="date"
                          value={lidEditForm.start_datum}
                          onChange={(e) =>
                            setLidEditForm((f) => ({ ...f, start_datum: e.target.value }))
                          }
                        />
                        <Input
                          label="Einddatum"
                          type="date"
                          value={lidEditForm.eind_datum}
                          onChange={(e) =>
                            setLidEditForm((f) => ({ ...f, eind_datum: e.target.value }))
                          }
                        />
                      </nldd-container>
                      <nldd-container layout="row" gap="8" horizontal-alignment="right">
                        <NlddButton variant="secondary" size="sm" onClick={cancelEditLid} text="Annuleren" />
                        <NlddButton
                          size="sm"
                          onClick={handleSaveLid}
                          loading={updateLidMutation.isPending}
                          text="Opslaan"
                        />
                      </nldd-container>
                    </nldd-container>
                  </nldd-list-item>
                );
              }
              // One text cell with everything but the name on its second
              // line. Before, two full-width containers split the row in
              // half, and the free-text expertise badge (a tag never
              // shrinks) spilled over the date on a phone.
              //
              // `-above-sm`: on a touch screen there is no hover, so the
              // buttons stay visible there. Plain `group-hover-reveal`
              // hid them at every width, which left no way to edit or
              // remove a lid on a phone.
              const sinds = `sinds ${formatDate(lid.start_datum)}`;
              const tot = lid.eind_datum
                ? `tot ${formatDate(lid.eind_datum)}`
                : null;
              const details = [lid.person_expertise, lid.rol, sinds, tot]
                .filter(Boolean)
                .join(' · ');
              return (
                <nldd-list-item key={lid.id} className="group">
                  <nldd-text-cell text={lid.person_naam} supporting-text={details} width="full" />
                  <nldd-cell className="group-hover-reveal-above-sm">
                    <NlddIconButton
                      icon="pencil"
                      accessibleLabel="Bewerken"
                      variant="neutral-transparent"
                      size="sm"
                      onClick={() => startEditLid(lid)}
                    />
                  </nldd-cell>
                  <nldd-cell className="group-hover-reveal-above-sm">
                    <NlddIconButton
                      icon="close"
                      accessibleLabel="Verwijderen"
                      variant="neutral-transparent"
                      size="sm"
                      onClick={() => setConfirmRemoveLidId(lid.id)}
                    />
                  </nldd-cell>
                </nldd-list-item>
              );
            })}
          </nldd-list>
        )}
        </nldd-container>
      </nldd-card>

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={handleDelete}
        title="Samenwerkingsverband verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={deleteMutation.isPending}
      >
        <nldd-rich-text>
          <p>
            Weet je zeker dat je <strong>{swv.naam}</strong> wilt verwijderen? Alle
            lidmaatschappen worden meegenomen.
          </p>
        </nldd-rich-text>
      </ConfirmDialog>

      <ConfirmDialog
        open={!!confirmRemoveLidId}
        onClose={() => setConfirmRemoveLidId(null)}
        onConfirm={handleRemoveLid}
        title="Lid verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={removeLidMutation.isPending}
      >
        Weet je zeker dat je dit lid wilt verwijderen?
      </ConfirmDialog>

      <PersonQuickCreateForm
        open={showPersonCreate}
        onClose={() => setShowPersonCreate(false)}
        initialName={personCreateName}
        onCreated={handlePersonCreated}
      />
    </nldd-container>
  );
}
