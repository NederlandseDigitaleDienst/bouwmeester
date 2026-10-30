import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useCreateOpdracht, useUpdateOpdracht, useAddOpdrachtNodeKoppeling, useRemoveOpdrachtNodeKoppeling } from '@/hooks/useOpdrachten';
import { useNodes } from '@/hooks/useNodes';
import { queryKeys } from '@/hooks/queryKeys';
import { usePeople } from '@/hooks/usePeople';
import { useOrganisatieFlat, useCreateOrganisatieEenheid } from '@/hooks/useOrganisatie';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { Input } from '@/components/common/Input';
import { Select } from '@/components/common/Select';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { buildPersonOptions } from '@/utils/personOptions';
import { Badge } from '@/components/common/Badge';
import { NieuwInstrumentDialog } from './NieuwInstrumentDialog';
import {
  OpdrachtType,
  OpdrachtStatus,
  Kostensoort,
  OPDRACHT_TYPE_LABELS,
  OPDRACHT_STATUS_LABELS,
  KOSTENSOORT_LABELS,
  NODE_TYPE_COLORS,
  NodeType,
  type Opdracht,
  type OpdrachtCreate,
  type OpdrachtUpdate,
  type OpdrachtNodeResponse,
  type CorpusNode,
} from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

interface OpdrachtFormProps {
  opdracht?: Opdracht;
  onClose: () => void;
  onSuccess: () => void;
  defaults?: { instrument_id?: string };
}

export function OpdrachtForm({ opdracht, onClose, onSuccess, defaults }: OpdrachtFormProps) {
  const isEdit = !!opdracht;
  const createMutation = useCreateOpdracht();
  const updateMutation = useUpdateOpdracht();
  const createOrganisatieEenheid = useCreateOrganisatieEenheid();
  const addKoppeling = useAddOpdrachtNodeKoppeling();
  const removeKoppeling = useRemoveOpdrachtNodeKoppeling();
  // limit=500 (backend max) so the instrument picker isn't truncated at the
  // default 100; the dropdown must show every instrument.
  const { data: instrumenten = [] } = useNodes(NodeType.INSTRUMENT, undefined, 500);
  const { data: allNodes = [] } = useNodes();
  const { data: people = [] } = usePeople();
  const { data: eenheden = [] } = useOrganisatieFlat();
  // Externe orgs zitten nu in dezelfde tabel als interne; filter op niet-synthetisch.
  const externeOrgs = eenheden.filter(
    (e) => e.bron !== 'synthetisch' && !['ministerie', 'directoraat_generaal', 'directie', 'afdeling', 'cluster', 'bureau', 'team'].includes(e.type),
  );
  const { currentPerson } = useCurrentPerson();
  const queryClient = useQueryClient();

  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({
    type: opdracht?.type || OpdrachtType.OPDRACHT,
    titel: opdracht?.titel || '',
    beschrijving: opdracht?.beschrijving || '',
    begrotingsjaar: opdracht?.begrotingsjaar || new Date().getFullYear(),
    budget: opdracht?.budget?.toString() || '',
    gerealiseerd: opdracht?.gerealiseerd?.toString() || '',
    kostensoort: opdracht?.kostensoort || '',
    volgend_jaar_benodigd: opdracht?.volgend_jaar_benodigd?.toString() || '',
    volgend_jaar_aangevraagd: opdracht?.volgend_jaar_aangevraagd?.toString() || '',
    instrument_id: opdracht?.instrument_id || defaults?.instrument_id || '',
    opdrachtnemer_eenheid_id: opdracht?.opdrachtnemer_eenheid_id || '',
    opdrachtgever_id: opdracht?.opdrachtgever_id || '',
    verantwoordelijke_id: opdracht?.verantwoordelijke_id || '',
    subsidieregeling: opdracht?.subsidieregeling || '',
    beschikking_nummer: opdracht?.beschikking_nummer || '',
    status: opdracht?.status || OpdrachtStatus.CONCEPT,
    referentie: opdracht?.referentie || '',
    startdatum: opdracht?.startdatum || '',
    einddatum: opdracht?.einddatum || '',
  });

  // Inline "nieuw instrument" dialog: opened from the instrument dropdown's
  // create action, prefilled with the text the user typed.
  // `seq` increments on every open so the dialog remounts and its title
  // field re-initialises from the freshly typed text (useState reads its
  // initial value only once per mount).
  const [instrumentDialog, setInstrumentDialog] = useState<{ open: boolean; titel: string; seq: number }>({
    open: false,
    titel: '',
    seq: 0,
  });

  const [koppelingen, setKoppelingen] = useState<OpdrachtNodeResponse[]>(opdracht?.node_koppelingen || []);
  const [newKoppelingNodeId, setNewKoppelingNodeId] = useState('');
  const [newKoppelingRelatie, setNewKoppelingRelatie] = useState('gerelateerd');

  const instrumentOptions: SelectOption[] = instrumenten.map(n => ({
    value: n.id,
    label: n.title,
  }));

  const opdrachtnemerOptions: SelectOption[] = externeOrgs.map(o => ({
    value: o.id,
    label: o.afkorting || o.naam,
    description: o.afkorting ? o.naam : undefined,
  }));

  const verantwoordelijkeOptions: SelectOption[] = buildPersonOptions(people, currentPerson);

  const opdrachtgeverOptions: SelectOption[] = eenheden.map(e => ({
    value: e.id,
    label: e.naam,
  }));

  const handleCreateOpdrachtnemer = async (text: string): Promise<string | null> => {
    // Nieuwe externe org wordt aangemaakt onder synthetische "Marktpartijen en
    // overige" parent (gezocht in eenheden); bron blijft handmatig.
    const marktpartijenParent = eenheden.find(
      (e) => e.bron === 'synthetisch' && e.naam === 'Marktpartijen en overige',
    );
    const result = await createOrganisatieEenheid.mutateAsync({
      naam: text,
      type: 'overig',
      parent_id: marktpartijenParent?.id ?? null,
    });
    return result?.id || null;
  };

  // Returns null: actual creation happens in the dialog, which sets the
  // instrument id via onChange on success. CreatableSelect treats a null
  // return as a soft success (closes + clears its query).
  const handleCreateInstrument = async (text: string): Promise<string | null> => {
    setInstrumentDialog(d => ({ open: true, titel: text, seq: d.seq + 1 }));
    return null;
  };

  const nodeOptions: SelectOption[] = allNodes
    .filter(n => !koppelingen.some(k => k.node_id === n.id))
    .map(n => ({
      value: n.id,
      label: n.title,
      description: n.node_type,
    }));

  const handleAddKoppeling = async () => {
    if (!newKoppelingNodeId || !opdracht) return;
    const result = await addKoppeling.mutateAsync({
      opdrachtId: opdracht.id,
      data: { node_id: newKoppelingNodeId, relatie_type: newKoppelingRelatie },
    });
    const selectedNode = allNodes.find(n => n.id === newKoppelingNodeId);
    setKoppelingen(prev => [...prev, {
      ...result,
      node_title: selectedNode?.title || null,
      node_type: selectedNode?.node_type || null,
    }]);
    setNewKoppelingNodeId('');
  };

  const handleRemoveKoppeling = async (koppelingId: string) => {
    if (!opdracht) return;
    await removeKoppeling.mutateAsync({ opdrachtId: opdracht.id, koppelingId });
    setKoppelingen(prev => prev.filter(k => k.id !== koppelingId));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.instrument_id) {
      setError('Selecteer een instrument.');
      return;
    }
    setError(null);
    const data = {
      type: form.type as OpdrachtType,
      titel: form.titel,
      beschrijving: form.beschrijving || undefined,
      begrotingsjaar: form.begrotingsjaar,
      budget: form.budget ? Number(form.budget) : undefined,
      gerealiseerd: form.gerealiseerd ? Number(form.gerealiseerd) : undefined,
      kostensoort: form.kostensoort ? (form.kostensoort as Kostensoort) : undefined,
      volgend_jaar_benodigd: form.volgend_jaar_benodigd ? Number(form.volgend_jaar_benodigd) : undefined,
      volgend_jaar_aangevraagd: form.volgend_jaar_aangevraagd ? Number(form.volgend_jaar_aangevraagd) : undefined,
      instrument_id: form.instrument_id,
      opdrachtnemer_eenheid_id: form.opdrachtnemer_eenheid_id || null,
      opdrachtgever_id: form.opdrachtgever_id || null,
      verantwoordelijke_id: form.verantwoordelijke_id || null,
      subsidieregeling: form.subsidieregeling || undefined,
      beschikking_nummer: form.beschikking_nummer || undefined,
      status: form.status as OpdrachtStatus,
      referentie: form.referentie || undefined,
      startdatum: form.startdatum || undefined,
      einddatum: form.einddatum || undefined,
    };

    try {
      if (isEdit && opdracht) {
        await updateMutation.mutateAsync({ id: opdracht.id, data: data as OpdrachtUpdate });
      } else {
        await createMutation.mutateAsync(data as OpdrachtCreate);
      }
      onSuccess();
    } catch {
      setError(isEdit ? 'Fout bij opslaan van opdracht.' : 'Fout bij aanmaken van opdracht.');
    }
  };

  const isSubsidie = form.type === OpdrachtType.SUBSIDIE;

  const formContent = (
    <nldd-form>
      <form onSubmit={handleSubmit}>
        <nldd-container gap="24">
        {/* Basic info */}
        <nldd-container layout="grid" gap="16">
          <Select
            label="Type"
            required
            value={form.type}
            onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
            options={Object.entries(OPDRACHT_TYPE_LABELS).map(([v, l]) => ({ value: v, label: l }))}
          />
          <Select
            label="Status"
            value={form.status}
            onChange={e => setForm(f => ({ ...f, status: e.target.value }))}
            options={Object.entries(OPDRACHT_STATUS_LABELS).map(([v, l]) => ({ value: v, label: l }))}
          />
        </nldd-container>

        <Input
          label="Titel"
          type="text"
          value={form.titel}
          onChange={e => setForm(f => ({ ...f, titel: e.target.value }))}
          required
        />

        <RichTextFormField
          label="Beschrijving"
          value={form.beschrijving}
          onChange={(value) => setForm(f => ({ ...f, beschrijving: value }))}
          rows={3}
        />

        {/* Links */}
        <nldd-container layout="grid" gap="16">
          <CreatableSelect
            label="Instrument"
            required
            value={form.instrument_id}
            onChange={(value) => setForm(f => ({ ...f, instrument_id: value }))}
            options={instrumentOptions}
            placeholder="Kies instrument..."
            onCreate={handleCreateInstrument}
            createLabel="Nieuw instrument"
          />
          <CreatableSelect
            label="Opdrachtnemer"
            value={form.opdrachtnemer_eenheid_id}
            onChange={(value) => setForm(f => ({ ...f, opdrachtnemer_eenheid_id: value }))}
            options={opdrachtnemerOptions}
            placeholder="Kies opdrachtnemer..."
            onCreate={handleCreateOpdrachtnemer}
            createLabel="Nieuwe organisatie"
            onClear={() => setForm(f => ({ ...f, opdrachtnemer_eenheid_id: '' }))}
          />
        </nldd-container>

        <nldd-container layout="grid" gap="16">
          <CreatableSelect
            label="Opdrachtgever"
            value={form.opdrachtgever_id}
            onChange={(value) => setForm(f => ({ ...f, opdrachtgever_id: value }))}
            options={opdrachtgeverOptions}
            placeholder="Kies opdrachtgever..."
            onClear={() => setForm(f => ({ ...f, opdrachtgever_id: '' }))}
          />
          <CreatableSelect
            label="Verantwoordelijke"
            value={form.verantwoordelijke_id}
            onChange={(value) => setForm(f => ({ ...f, verantwoordelijke_id: value }))}
            options={verantwoordelijkeOptions}
            placeholder="Kies verantwoordelijke..."
            onClear={() => setForm(f => ({ ...f, verantwoordelijke_id: '' }))}
          />
        </nldd-container>

        <Input
          label="Referentie"
          type="text"
          value={form.referentie}
          onChange={e => setForm(f => ({ ...f, referentie: e.target.value }))}
          placeholder="Intern kenmerk"
        />

        {/* Financial */}
        <nldd-form-section text="Financieel">
          <nldd-container layout="grid" gap="16">
            <Input
              label="Begrotingsjaar"
              type="number"
              value={form.begrotingsjaar}
              onChange={e => setForm(f => ({ ...f, begrotingsjaar: Number(e.target.value) }))}
              min={2020}
              max={2035}
              required
            />
            <Input
              label="Budget"
              type="number"
              value={form.budget}
              onChange={e => setForm(f => ({ ...f, budget: e.target.value }))}
              min={0}
              step="0.01"
            />
            <Input
              label="Gerealiseerd"
              type="number"
              value={form.gerealiseerd}
              onChange={e => setForm(f => ({ ...f, gerealiseerd: e.target.value }))}
              min={0}
              step="0.01"
            />
          </nldd-container>
          <nldd-container layout="grid" gap="16" padding-top="16">
            <Select
              label="Kostensoort"
              value={form.kostensoort}
              onChange={e => setForm(f => ({ ...f, kostensoort: e.target.value }))}
              placeholder="-"
              options={Object.entries(KOSTENSOORT_LABELS).map(([v, l]) => ({ value: v, label: l }))}
            />
            <Input
              label="Volgend jaar benodigd"
              type="number"
              value={form.volgend_jaar_benodigd}
              onChange={e => setForm(f => ({ ...f, volgend_jaar_benodigd: e.target.value }))}
              min={0}
              step="0.01"
            />
            <Input
              label="Volgend jaar aangevraagd"
              type="number"
              value={form.volgend_jaar_aangevraagd}
              onChange={e => setForm(f => ({ ...f, volgend_jaar_aangevraagd: e.target.value }))}
              min={0}
              step="0.01"
            />
          </nldd-container>
        </nldd-form-section>

        {/* Dates */}
        <nldd-container layout="grid" gap="16">
          <Input
            label="Startdatum"
            type="date"
            value={form.startdatum}
            onChange={e => setForm(f => ({ ...f, startdatum: e.target.value }))}
          />
          <Input
            label="Einddatum"
            type="date"
            value={form.einddatum}
            onChange={e => setForm(f => ({ ...f, einddatum: e.target.value }))}
          />
        </nldd-container>

        {/* Subsidie-specific */}
        {isSubsidie && (
          <nldd-form-section text="Subsidie-specifiek">
            <nldd-container layout="grid" gap="16">
              <Input
                label="Subsidieregeling"
                type="text"
                value={form.subsidieregeling}
                onChange={e => setForm(f => ({ ...f, subsidieregeling: e.target.value }))}
              />
              <Input
                label="Beschikking nummer"
                type="text"
                value={form.beschikking_nummer}
                onChange={e => setForm(f => ({ ...f, beschikking_nummer: e.target.value }))}
              />
            </nldd-container>
          </nldd-form-section>
        )}

        {/* Node koppelingen (edit mode only) */}
        {isEdit && opdracht && (
          <nldd-form-section text="Gekoppelde nodes">
            <nldd-container gap="12">
              {koppelingen.length > 0 && (
                <nldd-list appearance="box-tinted" dividers="never">
                  {koppelingen.map(k => (
                    <nldd-list-item key={k.id}>
                      {k.node_type && (
                        <nldd-text-cell width="fit-content">
                          <Badge color={NODE_TYPE_COLORS[k.node_type as NodeType] ?? 'coolgray'} dot>
                            {k.node_type}
                          </Badge>
                        </nldd-text-cell>
                      )}
                      <nldd-text-cell text={k.node_title || k.node_id} overline={k.relatie_type ?? undefined} />
                      <NlddIconButton
                        icon="trash"
                        variant="neutral-transparent"
                        size="sm"
                        accessibleLabel="Koppeling verwijderen"
                        onClick={() => handleRemoveKoppeling(k.id)}
                      />
                    </nldd-list-item>
                  ))}
                </nldd-list>
              )}
              <nldd-container layout="row" gap="8" vertical-alignment="bottom">
                <nldd-container width="fit-content" className="row-fill">
                  <CreatableSelect
                    label="Node"
                    value={newKoppelingNodeId}
                    onChange={setNewKoppelingNodeId}
                    options={nodeOptions}
                    placeholder="Zoek node..."
                  />
                </nldd-container>
                <nldd-container width="160px">
                  <Select
                    label="Relatie"
                    value={newKoppelingRelatie}
                    onChange={e => setNewKoppelingRelatie(e.target.value)}
                    options={[
                      { value: 'gerelateerd', label: 'Gerelateerd' },
                      { value: 'levert_aan', label: 'Levert aan' },
                      { value: 'onderdeel_van', label: 'Onderdeel van' },
                    ]}
                  />
                </nldd-container>
                <NlddButton
                  type="button"
                  startIcon="plus"
                  disabled={!newKoppelingNodeId || addKoppeling.isPending}
                  onClick={handleAddKoppeling}
                  text="Toevoegen"
                />
              </nldd-container>
            </nldd-container>
          </nldd-form-section>
        )}

        {/* Error feedback */}
        {error && <nldd-banner variant="critical" size="sm" text={error} />}

        {/* Submit */}
        <nldd-form-actions>
          <nldd-button-group orientation="horizontal">
            <NlddButton type="button" variant="secondary" onClick={onClose} text="Annuleren" />
            <NlddButton type="submit" disabled={createMutation.isPending || updateMutation.isPending} text={isEdit ? 'Opslaan' : 'Aanmaken'} />
          </nldd-button-group>
        </nldd-form-actions>
        </nldd-container>
      </form>
    </nldd-form>
  );

  return (
    <>
      {formContent}
      <NieuwInstrumentDialog
        key={instrumentDialog.seq}
        open={instrumentDialog.open}
        initialTitle={instrumentDialog.titel}
        onClose={() => setInstrumentDialog(d => ({ ...d, open: false, titel: '' }))}
        onCreated={(node: CorpusNode) => {
          // Seed the just-created instrument into the same cached list the
          // dropdown reads from, so its label shows immediately instead of
          // a blank field until useCreateNode's invalidation refetches.
          queryClient.setQueryData<CorpusNode[]>(
            queryKeys.nodes.list(NodeType.INSTRUMENT, undefined, 500),
            (prev) => (prev ? [...prev, node] : [node]),
          );
          setForm(f => ({ ...f, instrument_id: node.id }));
          setInstrumentDialog(d => ({ ...d, open: false, titel: '' }));
        }}
      />
    </>
  );
}
