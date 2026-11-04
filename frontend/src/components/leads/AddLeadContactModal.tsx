import { useState, useCallback, useEffect } from 'react';

import { Modal } from '@/components/common/Modal';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { usePeople } from '@/hooks/usePeople';
import { useAddLeadContact } from '@/hooks/useLeads';
import { useCreateContactPerson } from '@/hooks/useNewContactPerson';
import { NewContactPersonFields } from '@/components/leads/NewContactPersonFields';
import {
  emptyContactPersonFields,
  type ContactPersonFieldsState,
} from '@/components/leads/contactPersonFields';
import { LEAD_CONTACT_ROL_LABELS } from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

const DEFAULT_CONTACT_ROLLEN: SelectOption[] = Object.entries(
  LEAD_CONTACT_ROL_LABELS,
).map(([value, label]) => ({ value, label }));

interface Props {
  leadId: string | null;
  onClose: () => void;
  /** Rol die voorgeselecteerd staat; default de externe contactpersoon. */
  defaultRol?: string;
  /** Rollen om uit te kiezen; default alle lead-contactrollen. */
  rolLabels?: Record<string, string>;
  /** Titel van de modal in de keuzestand. */
  title?: string;
  /**
   * Beperk de kiezer tot deze personen (bijvoorbeeld de leden van het
   * initiatief). Zonder deze prop zijn alle personen kiesbaar.
   */
  candidates?: Candidate[];
  /** Toelichting boven de kiezer, bijvoorbeeld waarom de lijst beperkt is. */
  hint?: string;
  /** Sta "nieuwe persoon aanmaken" toe. Voor een casusteam staat dit uit. */
  allowCreate?: boolean;
}

export interface Candidate {
  id: string;
  naam: string;
  functie?: string | null;
  expertise?: string | null;
}

type Mode = 'select' | 'create';

export function AddLeadContactModal({
  leadId,
  onClose,
  defaultRol = 'contactpersoon',
  rolLabels,
  title = 'Externe contactpersoon toevoegen',
  candidates,
  hint,
  allowCreate = true,
}: Props) {
  const { data: allPeople = [] } = usePeople();
  const people: Candidate[] = candidates ?? allPeople;
  const addContact = useAddLeadContact();
  const createContact = useCreateContactPerson();

  const baseRollen: SelectOption[] = rolLabels
    ? Object.entries(rolLabels).map(([value, label]) => ({ value, label }))
    : DEFAULT_CONTACT_ROLLEN;

  const [mode, setMode] = useState<Mode>('select');
  const [personId, setPersonId] = useState('');
  const [rol, setRol] = useState(defaultRol);
  const [fields, setFields] = useState<ContactPersonFieldsState>(emptyContactPersonFields);
  const [extraRollen, setExtraRollen] = useState<SelectOption[]>([]);

  const rolOptions: SelectOption[] = [...baseRollen, ...extraRollen];

  const handleCreateRol = useCallback(
    async (text: string): Promise<string | null> => {
      const value = text.trim();
      if (!value) return null;
      // Sla de getypte tekst zelf op als rol-waarde. Geen slug-conversie:
      // ResourcePermission.rol is een vrij stringveld en LeadDetailPanel
      // toont de raw waarde als fallback. Een slug zou diakriet/haakjes
      // verminken zonder voordeel.
      setExtraRollen((prev) =>
        prev.some((o) => o.value === value) ||
        baseRollen.some((o) => o.value === value)
          ? prev
          : [...prev, { value, label: value }],
      );
      setRol(value);
      return value;
    },
    [baseRollen],
  );

  // Reset alle state bij elke lead-wissel én bij sluiten van de modal,
  // zodat eerder ingevulde "nieuwe contact"-velden niet doorlekken naar
  // een volgende lead.
  useEffect(() => {
    if (!leadId) return;
    setMode('select');
    setPersonId('');
    setRol(defaultRol);
    setFields(emptyContactPersonFields());
    setExtraRollen([]);
  }, [leadId, defaultRol]);

  const personOptions: SelectOption[] = people.map((p) => {
    const parts = [p.functie, p.expertise].filter((v): v is string => !!v);
    return {
      value: p.id,
      label: p.naam,
      description: parts.length > 0 ? parts.join(' · ') : undefined,
    };
  });

  const switchToCreate = useCallback((typedName: string) => {
    setMode('create');
    setFields({ ...emptyContactPersonFields(), naam: typedName });
    return null;
  }, []);

  const resetAndClose = useCallback(() => {
    setMode('select');
    setPersonId('');
    setRol(defaultRol);
    setFields(emptyContactPersonFields());
    setExtraRollen([]);
    onClose();
  }, [onClose, defaultRol]);

  const handleSubmitSelect = useCallback(async () => {
    if (!leadId || !personId) return;
    try {
      await addContact.mutateAsync({ leadId, personId, rol });
      resetAndClose();
    } catch {
      // toast wordt al getoond
    }
  }, [leadId, personId, rol, addContact, resetAndClose]);

  const handleSubmitCreate = useCallback(async () => {
    if (!leadId) return;
    const result = await createContact.create({
      naam: fields.naam,
      email: fields.email,
      phone: fields.phone,
      functie: fields.functie,
      expertise: fields.expertise,
      organisatieEenheidId: fields.organisatieEenheidId || undefined,
      samenwerkingsverbandIds: Array.from(fields.samenwerkingsverbandIds),
    });
    if (!result) return; // toast getoond, modal blijft open
    try {
      await addContact.mutateAsync({ leadId, personId: result.personId, rol });
      resetAndClose();
    } catch {
      // toast
    }
  }, [leadId, fields, rol, createContact, addContact, resetAndClose]);

  const isPending = createContact.isPending || addContact.isPending;

  return (
    <Modal
      open={!!leadId}
      onClose={resetAndClose}
      title={mode === 'create' ? 'Nieuwe contactpersoon' : title}
      size="md"
      closeable={!isPending}
      footer={
        mode === 'create' ? (
          <>
            <NlddButton variant="secondary" onClick={() => setMode('select')} text="Terug" />
            <NlddButton
              onClick={handleSubmitCreate}
              loading={isPending}
              disabled={!fields.naam.trim()}
              text="Aanmaken & koppelen"
            />
          </>
        ) : (
          <>
            <NlddButton variant="secondary" onClick={resetAndClose} text="Annuleren" />
            <NlddButton
              onClick={handleSubmitSelect}
              loading={addContact.isPending}
              disabled={!personId}
              text="Toevoegen"
            />
          </>
        )
      }
    >
      {mode === 'select' ? (
        <nldd-container gap="16">
          {hint && (
            <nldd-text size="sm" color="secondary">{hint}</nldd-text>
          )}
          <CreatableSelect
            label="Persoon"
            value={personId}
            onChange={setPersonId}
            options={personOptions}
            placeholder={allowCreate ? 'Zoek of maak een persoon...' : 'Zoek een persoon...'}
            {...(allowCreate
              ? {
                  onCreate: async (name: string) => switchToCreate(name),
                  createLabel: 'Nieuwe persoon aanmaken',
                }
              : {})}
            required
          />
          <CreatableSelect
            label="Rol"
            value={rol}
            onChange={setRol}
            options={rolOptions}
            placeholder="Selecteer of typ een rol..."
            onCreate={handleCreateRol}
            createLabel="Nieuwe rol toevoegen"
          />
        </nldd-container>
      ) : (
        <nldd-container gap="16">
          <NewContactPersonFields
            state={fields}
            onChange={setFields}
            disabled={isPending}
          />
          <CreatableSelect
            label="Rol op deze lead"
            value={rol}
            onChange={setRol}
            options={rolOptions}
            placeholder="Selecteer of typ een rol..."
            onCreate={handleCreateRol}
            createLabel="Nieuwe rol toevoegen"
          />
        </nldd-container>
      )}
    </Modal>
  );
}
