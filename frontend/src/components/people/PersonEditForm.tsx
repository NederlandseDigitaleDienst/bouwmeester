import { useState, useEffect, useRef } from 'react';
import { useCopyToClipboard } from '@/hooks/useCopyToClipboard';
import { Modal } from '@/components/common/Modal';
import { Input } from '@/components/common/Input';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { Select } from '@/components/common/Select';
import { CascadingOrgSelect } from '@/components/common/CascadingOrgSelect';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { Icon } from '@/components/nldd/Icon';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent, useNlddValue } from '@/components/nldd/events';
import {
  usePeople,
  usePerson,
  useSearchPeople,
  useRotateApiKey,
  useAddPersonEmail,
  useRemovePersonEmail,
  useSetDefaultEmail,
  useAddPersonPhone,
  useRemovePersonPhone,
  useSetDefaultPhone,
  useExpertiseValues,
} from '@/hooks/usePeople';
import { FUNCTIE_LABELS, DIENSTVERBAND_LABELS, PHONE_LABELS, formatFunctie } from '@/types';
import type { Person, PersonFormSubmitParams } from '@/types';
import { errorDetail } from '@/api/client';
import { matchEmailOrganisatie } from '@/api/people';
import { usePermissions } from '@/hooks/usePermissions';
import { NlddButton } from '@/components/nldd/NlddButton';

// Character names from Bordewijk's novel "Karakter" — used as agent names
const KARAKTER_NAMEN = [
  // Hoofdpersonen
  'Dreverhaven', 'Katadreuffe', 'Joba',
  // Kantoor & juridisch
  'Stroomkoning', 'De Gankelaar', 'Rentenstein', 'Carlion', 'Schuwagt',
  'Lorna te George', 'Graanoogst', 'Piaat',
  // Overige personages
  'Jan Maan', 'Harm Knol Hein', 'De Merree', 'Kalvelage', 'Sibculo',
  'Hamerslag', 'Den Hieperboree', 'Wever', 'Kees Adam',
  'Burgeik', 'Van den Born', 'Iris',
];

const DEFAULT_FUNCTIE_OPTIONS: SelectOption[] = Object.entries(FUNCTIE_LABELS).map(
  ([value, label]) => ({ value, label })
);

const PHONE_LABEL_OPTIONS = Object.entries(PHONE_LABELS).map(([value, label]) => ({ value, label }));
const DIENSTVERBAND_OPTIONS = Object.entries(DIENSTVERBAND_LABELS).map(([value, label]) => ({
  value,
  label,
}));

interface EmailRowProps {
  email: string;
  isDefault: boolean;
  onSetDefault: () => void;
  onRemove: () => void;
}

/** One row of the email-management list: the address, a star to mark it
 *  default, and a delete action — both as list-item-segments per the
 *  established row-with-actions pattern (see LeadInboxView). */
function EmailRow({ email, isDefault, onSetDefault, onRemove }: EmailRowProps) {
  const starRef = useRef<HTMLElement>(null);
  const removeRef = useRef<HTMLElement>(null);
  useNlddEvent(starRef, 'click', onSetDefault);
  useNlddEvent(removeRef, 'click', onRemove);

  return (
    <nldd-list-item>
      <nldd-text-cell text={email} width="full" />
      <nldd-list-item-segment
        ref={starRef}
        button
        accessible-label={isDefault ? 'Standaard e-mailadres' : 'Instellen als standaard'}
      >
        {/* The Icon wrapper has no color prop, so the raw element is used
            here to reach nldd-icon's own `color`: 'warning' for the starred
            default, unset (inherits secondary) otherwise. */}
        <nldd-icon icon="star" size="16" {...(isDefault ? { color: 'warning' } : {})} aria-hidden="true" />
      </nldd-list-item-segment>
      <nldd-list-item-segment ref={removeRef} button accessible-label="E-mailadres verwijderen">
        <Icon name="close" size="sm" />
      </nldd-list-item-segment>
    </nldd-list-item>
  );
}

interface PhoneRowProps {
  phoneNumber: string;
  label: string;
  isDefault: boolean;
  onSetDefault: () => void;
  onRemove: () => void;
}

function PhoneRow({ phoneNumber, label, isDefault, onSetDefault, onRemove }: PhoneRowProps) {
  const starRef = useRef<HTMLElement>(null);
  const removeRef = useRef<HTMLElement>(null);
  useNlddEvent(starRef, 'click', onSetDefault);
  useNlddEvent(removeRef, 'click', onRemove);

  return (
    <nldd-list-item>
      <nldd-text-cell text={phoneNumber} supporting-text={label} width="full" />
      <nldd-list-item-segment
        ref={starRef}
        button
        accessible-label={isDefault ? 'Standaard telefoonnummer' : 'Instellen als standaard'}
      >
        <nldd-icon icon="star" size="16" {...(isDefault ? { color: 'warning' } : {})} aria-hidden="true" />
      </nldd-list-item-segment>
      <nldd-list-item-segment ref={removeRef} button accessible-label="Telefoonnummer verwijderen">
        <Icon name="close" size="sm" />
      </nldd-list-item-segment>
    </nldd-list-item>
  );
}

interface NewValueFieldProps {
  type: 'email' | 'tel';
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder: string;
  accessibleLabel: string;
}

/** A single `nldd-text-field` for a new email/phone value, submitting on
 *  Enter — the design-system field has no form of its own to catch the
 *  implicit-submission rule, so Enter is wired by hand here. */
function NewValueField({ type, value, onChange, onSubmit, placeholder, accessibleLabel }: NewValueFieldProps) {
  const ref = useRef<HTMLElement & { value?: string }>(null);
  useNlddValue(ref, value);
  useNlddEvent(ref, 'input', (e) => onChange(eventValue(e)));
  useNlddEvent(
    ref,
    'keydown',
    (e) => {
      if ((e as KeyboardEvent).key === 'Enter') {
        e.preventDefault();
        onSubmit();
      }
    },
  );

  return (
    <nldd-text-field
      ref={ref}
      type={type === 'tel' ? 'tel' : 'email'}
      placeholder={placeholder}
      accessible-label={accessibleLabel}
      autocomplete={type === 'tel' ? 'tel' : 'email'}
    />
  );
}

interface PersonEditFormProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (params: PersonFormSubmitParams) => void;
  isLoading?: boolean;
  editData?: Person | null;
  defaultIsAgent?: boolean;
  /** Pre-fill the org unit selector (e.g. when adding from within an org unit) */
  defaultOrgEenheidId?: string;
  /** One-time API key to display after creation */
  createdApiKey?: string | null;
}

export function PersonEditForm({
  open,
  onClose,
  onSubmit,
  isLoading,
  editData,
  defaultIsAgent = false,
  defaultOrgEenheidId,
  createdApiKey,
}: PersonEditFormProps) {
  const [naam, setNaam] = useState('');
  const [email, setEmail] = useState('');
  const [functie, setFunctie] = useState('');
  const [expertise, setExpertise] = useState('');
  const [description, setDescription] = useState('');
  const [orgEenheidId, setOrgEenheidId] = useState('');
  const [dienstverband, setDienstverband] = useState('in_dienst');
  const [emailTouched, setEmailTouched] = useState(false);
  const [emailMatch, setEmailMatch] = useState<{
    organisatie_eenheid_id: string;
    organisatie_naam: string;
  } | null>(null);

  // Debounced email-domein -> OrganisatieEenheid lookup via RIO
  useEffect(() => {
    if (!email || !email.includes('@') || orgEenheidId) {
      setEmailMatch(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const res = await matchEmailOrganisatie(email);
        if (res.matched && res.organisatie_eenheid_id && res.organisatie_naam) {
          setEmailMatch({
            organisatie_eenheid_id: res.organisatie_eenheid_id,
            organisatie_naam: res.organisatie_naam,
          });
        } else {
          setEmailMatch(null);
        }
      } catch {
        setEmailMatch(null);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [email, orgEenheidId]);
  const [functieOptions, setFunctieOptions] = useState<SelectOption[]>(DEFAULT_FUNCTIE_OPTIONS);
  const [expertiseLocalAdded, setExpertiseLocalAdded] = useState<string[]>([]);
  const { data: expertiseValues = [] } = useExpertiseValues();

  // Rotated API key one-time display
  const [rotatedApiKey, setRotatedApiKey] = useState<string | null>(null);
  const { copied, copy } = useCopyToClipboard();
  const [showKey, setShowKey] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const rotateApiKeyMutation = useRotateApiKey();
  const { isSuperAdmin } = usePermissions();

  // Search/select existing person state (create mode, non-agent only)
  const [selectedPerson, setSelectedPerson] = useState<Person | null>(null);
  const [naamQuery, setNaamQuery] = useState('');

  // Email/phone inline management state (edit mode)
  const [newEmail, setNewEmail] = useState('');
  const [newEmailError, setNewEmailError] = useState('');
  const [newPhone, setNewPhone] = useState('');
  const [newPhoneLabel, setNewPhoneLabel] = useState('werk');
  const [newPhoneError, setNewPhoneError] = useState('');

  const { data: allPeople = [] } = usePeople();
  const { data: searchResults = [] } = useSearchPeople(naamQuery);
  const { data: freshPerson } = usePerson(editData?.id ?? null);

  // Email/phone mutation hooks
  const addEmailMutation = useAddPersonEmail();
  const removeEmailMutation = useRemovePersonEmail();
  const setDefaultEmailMutation = useSetDefaultEmail();
  const addPhoneMutation = useAddPersonPhone();
  const removePhoneMutation = useRemovePersonPhone();
  const setDefaultPhoneMutation = useSetDefaultPhone();

  // Use fresh person data for emails/phones (auto-refreshed by React Query invalidation)
  const personEmails = freshPerson?.emails ?? editData?.emails ?? [];
  const personPhones = freshPerson?.phones ?? editData?.phones ?? [];

  // Cache all persons we've ever seen from search results so lookups
  // remain stable even when the debounced query changes (Fix #3).
  const personCacheRef = useRef<Map<string, Person>>(new Map());
  for (const p of searchResults) {
    personCacheRef.current.set(p.id, p);
  }

  // Filter out agents from search results
  const personResults = searchResults.filter(p => !p.is_agent);

  // Build options for the naam CreatableSelect
  const naamOptions: SelectOption[] = personResults.map(p => ({
    value: p.id,
    label: p.naam,
    description: p.default_email || p.email || undefined,
  }));

  const naamEmptyMessage = naamQuery.length < 2
    ? 'Typ minimaal 2 tekens om te zoeken...'
    : 'Geen personen gevonden';

  // The key to display — either freshly rotated, freshly created, or nothing.
  const displayApiKey = rotatedApiKey || createdApiKey || null;

  useEffect(() => {
    if (open) {
      setRotatedApiKey(null);
      setShowKey(false);
      setConfirmRotate(false);
      setNewEmail('');
      setNewEmailError('');
      setNewPhone('');
      setNewPhoneLabel('werk');
      setNewPhoneError('');
      if (editData) {
        setNaam(editData.naam);
        setEmail(editData.email || '');
        setFunctie(editData.functie || '');
        setExpertise(editData.expertise || '');
        setDescription(editData.description || '');
        setOrgEenheidId('');
        // Ensure the existing functie value is in options
        if (editData.functie) {
          setFunctieOptions((prev) =>
            prev.some((o) => o.value === editData.functie)
              ? prev
              : [...prev, { value: editData.functie!, label: formatFunctie(editData.functie!) || editData.functie! }],
          );
        }
      } else {
        // For new agents, pick next available Karakter name
        if (defaultIsAgent) {
          const usedNames = new Set(allPeople.filter(p => p.is_agent).map(p => p.naam));
          const nextName = KARAKTER_NAMEN.find(n => !usedNames.has(n)) || '';
          setNaam(nextName);
        } else {
          setNaam('');
        }
        setEmail('');
        setFunctie('');
        setExpertise('');
        setDescription('');
        setOrgEenheidId(defaultOrgEenheidId || '');
        setDienstverband('in_dienst');
        setSelectedPerson(null);
        setNaamQuery('');
        setEmailTouched(false);
        personCacheRef.current.clear();
      }
    }
  }, [open, editData, defaultIsAgent, defaultOrgEenheidId, allPeople]);

  const isAgent = editData ? editData.is_agent : defaultIsAgent;
  const isCreateMode = !editData;
  const isEditMode = !!editData;

  const isValid = selectedPerson
    ? true // existing person is always valid
    : isEditMode
      ? !!naam.trim() // edit mode: only naam required (emails managed separately)
      : naam.trim() && (isAgent || email.trim()); // create mode: naam + email (unless agent)

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!isValid) return;

    if (editData) {
      onSubmit({
        kind: 'edit',
        personId: editData.id,
        data: {
          naam: naam.trim(),
          // In edit mode, don't send email — managed via multi-email section
          functie: isAgent ? undefined : (functie || undefined),
          expertise: isAgent ? undefined : (expertise.trim() || undefined),
          description: isAgent ? (description.trim() || undefined) : undefined,
          is_agent: isAgent,
        },
      });
    } else if (selectedPerson) {
      onSubmit({
        kind: 'link',
        existingPersonId: selectedPerson.id,
        orgEenheidId: orgEenheidId || undefined,
        dienstverband: orgEenheidId ? dienstverband : undefined,
      });
    } else {
      onSubmit({
        kind: 'create',
        data: {
          naam: naam.trim(),
          email: email.trim() || undefined,
          functie: isAgent ? undefined : (functie || undefined),
          expertise: isAgent ? undefined : (expertise.trim() || undefined),
          description: isAgent ? (description.trim() || undefined) : undefined,
          is_agent: isAgent,
        },
        orgEenheidId: orgEenheidId || undefined,
        dienstverband: orgEenheidId ? dienstverband : undefined,
      });
    }
  };

  const handleCreateFunctie = async (text: string): Promise<string | null> => {
    const value = text.toLowerCase().replace(/\s+/g, '_');
    setFunctieOptions((prev) => [...prev, { value, label: text }]);
    setFunctie(value);
    return value;
  };

  // Handle selecting an existing person from the search dropdown
  const handleNaamSelect = (personId: string) => {
    // Look up in cache first (stable across debounce cycles), then fallback to current results
    const person = personCacheRef.current.get(personId) || personResults.find(p => p.id === personId);
    if (person) {
      setSelectedPerson(person);
      setNaam(person.naam);
      setEmail(person.default_email || person.email || '');
      setFunctie(person.functie || '');
      setExpertise(person.expertise || '');
      // Ensure the functie value is in options
      if (person.functie) {
        setFunctieOptions((prev) =>
          prev.some((o) => o.value === person.functie)
            ? prev
            : [...prev, { value: person.functie!, label: formatFunctie(person.functie!) || person.functie! }],
        );
      }
    }
  };

  // Handle creating a new person (typed name not found in results)
  const handleNaamCreate = async (text: string): Promise<string | null> => {
    setSelectedPerson(null);
    setNaam(text);
    setEmail('');
    setFunctie('');
    setExpertise('');
    return null; // don't set a value — we switch to create mode
  };

  // Clear selected person and return to search/create mode
  const handleNaamClear = () => {
    setSelectedPerson(null);
    setNaam('');
    setEmail('');
    setFunctie('');
    setExpertise('');
    setNaamQuery('');
  };

  const handleCopyKey = async () => {
    if (displayApiKey) {
      const ok = await copy(displayApiKey);
      if (!ok) {
        // Clipboard API unavailable — show the key so user can copy manually.
        setShowKey(true);
      }
    }
  };

  const handleRotateKey = async () => {
    if (!editData) return;
    if (!confirmRotate) {
      setConfirmRotate(true);
      return;
    }
    try {
      const result = await rotateApiKeyMutation.mutateAsync(editData.id);
      setRotatedApiKey(result.api_key);
      setConfirmRotate(false);
    } catch {
      setConfirmRotate(false);
    }
  };

  // Email management handlers
  const handleAddEmail = async () => {
    if (!editData || !newEmail.trim()) return;
    setNewEmailError('');
    try {
      await addEmailMutation.mutateAsync({
        personId: editData.id,
        data: { email: newEmail.trim() },
      });
      setNewEmail('');
    } catch (error) {
      // The backend says why: taken, invalid, or not yours to change.
      setNewEmailError(errorDetail(error) || 'Ongeldig of bestaand e-mailadres');
    }
  };

  const handleRemoveEmail = async (emailId: string) => {
    if (!editData) return;
    await removeEmailMutation.mutateAsync({ personId: editData.id, emailId });
  };

  const handleSetDefaultEmail = async (emailId: string) => {
    if (!editData) return;
    await setDefaultEmailMutation.mutateAsync({ personId: editData.id, emailId });
  };

  // Phone management handlers
  const handleAddPhone = async () => {
    if (!editData || !newPhone.trim()) return;
    setNewPhoneError('');
    try {
      await addPhoneMutation.mutateAsync({
        personId: editData.id,
        data: { phone_number: newPhone.trim(), label: newPhoneLabel },
      });
      setNewPhone('');
      setNewPhoneLabel('werk');
    } catch (error) {
      setNewPhoneError(errorDetail(error) || 'Ongeldig of bestaand telefoonnummer');
    }
  };

  const handleRemovePhone = async (phoneId: string) => {
    if (!editData) return;
    await removePhoneMutation.mutateAsync({ personId: editData.id, phoneId });
  };

  const handleSetDefaultPhone = async (phoneId: string) => {
    if (!editData) return;
    await setDefaultPhoneMutation.mutateAsync({ personId: editData.id, phoneId });
  };

  const title = editData
    ? (isAgent ? 'Agent bewerken' : 'Persoon bewerken')
    : selectedPerson
      ? 'Persoon koppelen'
      : (isAgent ? 'Agent toevoegen' : 'Persoon toevoegen');

  const submitLabel = editData
    ? 'Opslaan'
    : selectedPerson
      ? 'Koppelen'
      : 'Toevoegen';

  // When a one-time API key is displayed, prevent accidental close.
  const isShowingKey = !!displayApiKey;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      closeable={!isShowingKey}
      footer={
        isShowingKey ? (
          <NlddButton onClick={onClose} text="Ik heb de sleutel gekopieerd" />
        ) : (
          <>
            <NlddButton variant="secondary" onClick={onClose} text="Annuleren" />
            <NlddButton
              onClick={handleSubmit}
              loading={isLoading}
              disabled={!isValid}
              text={submitLabel}
            />
          </>
        )
      }
    >
      {/*
        The submit/cancel buttons live in Modal's `footer`, rendered as a
        sibling of `children` rather than inside this form — so they are not
        descendants of `nldd-form` and `nldd-form-actions` cannot reach them
        here. Wrapping the field body still gets light-DOM autofill and
        label-alignment inheritance for any nldd-form-field/-section inside.
      */}
      <nldd-form>
      <form onSubmit={handleSubmit}>
      <nldd-container gap="16">
        {/* Naam field: search+select in create mode for non-agents, plain Input otherwise */}
        {isCreateMode && !isAgent ? (
          <CreatableSelect
            label="Naam"
            value={selectedPerson?.id || ''}
            onChange={handleNaamSelect}
            options={naamOptions}
            placeholder="Zoek persoon of typ nieuwe naam..."
            onCreate={handleNaamCreate}
            createLabel="Nieuwe persoon aanmaken"
            onQueryChange={setNaamQuery}
            filterLocally={false}
            displayValue={naam}
            onClear={selectedPerson ? handleNaamClear : undefined}
            emptyMessage={naamEmptyMessage}
            required
          />
        ) : (
          <Input
            label="Naam"
            value={naam}
            onChange={(e) => setNaam(e.target.value)}
            placeholder="Volledige naam"
            autoComplete="name"
            required
            autoFocus
          />
        )}

        {/* Email field — create mode (non-agent): single input; edit mode: managed list */}
        {!isAgent && isCreateMode && selectedPerson && (
          <Input
            label="E-mail"
            type="email"
            value={email || 'Geen e-mail'}
            onChange={() => {}}
            disabled
          />
        )}
        {!isAgent && isCreateMode && !selectedPerson && (
          <>
            <Input
              label="E-mail"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => setEmailTouched(true)}
              placeholder="email@voorbeeld.nl"
              autoComplete="email"
              required
              error={emailTouched && !email.trim() ? 'E-mail is verplicht' : undefined}
            />
            {emailMatch && (
              <nldd-inline-dialog
                variant="alert"
                text={`Domein wijst naar ${emailMatch.organisatie_naam}`}
                horizontal-alignment="left"
              >
                <div slot="actions">
                  <NlddButton
                    text="Koppel als organisatie"
                    variant="neutral-transparent"
                    size="sm"
                    onClick={() => {
                      setOrgEenheidId(emailMatch.organisatie_eenheid_id);
                      setDienstverband('extern');
                      setEmailMatch(null);
                    }}
                  />
                </div>
              </nldd-inline-dialog>
            )}
          </>
        )}

        {/* Email management — edit mode, non-agent */}
        {!isAgent && isEditMode && (
          <nldd-container gap="8">
            <nldd-text weight="medium">E-mailadressen</nldd-text>
            {personEmails.length === 0 ? (
              <nldd-text size="sm" color="secondary">Geen e-mailadressen</nldd-text>
            ) : (
              <nldd-list appearance="box-tinted" accessible-label="E-mailadressen">
                {personEmails.map((em) => (
                  <EmailRow
                    key={em.id}
                    email={em.email}
                    isDefault={em.is_default}
                    onSetDefault={() => handleSetDefaultEmail(em.id)}
                    onRemove={() => handleRemoveEmail(em.id)}
                  />
                ))}
              </nldd-list>
            )}
            <nldd-container layout="row" gap="8" vertical-alignment="center">
              <nldd-container width="full">
                <NewValueField
                  type="email"
                  value={newEmail}
                  onChange={(v) => { setNewEmail(v); setNewEmailError(''); }}
                  onSubmit={handleAddEmail}
                  placeholder="Nieuw e-mailadres..."
                  accessibleLabel="Nieuw e-mailadres"
                />
              </nldd-container>
              <NlddIconButton
                icon="plus"
                accessibleLabel="E-mailadres toevoegen"
                variant="secondary"
                disabled={!newEmail.trim() || addEmailMutation.isPending}
                onClick={handleAddEmail}
              />
            </nldd-container>
            {newEmailError && (
              <nldd-text size="xs" color="critical">{newEmailError}</nldd-text>
            )}
          </nldd-container>
        )}

        {/* Phone management — edit mode, non-agent */}
        {!isAgent && isEditMode && (
          <nldd-container gap="8">
            <nldd-text weight="medium">Telefoonnummers</nldd-text>
            {personPhones.length === 0 ? (
              <nldd-text size="sm" color="secondary">Geen telefoonnummers</nldd-text>
            ) : (
              <nldd-list appearance="box-tinted" accessible-label="Telefoonnummers">
                {personPhones.map((ph) => (
                  <PhoneRow
                    key={ph.id}
                    phoneNumber={ph.phone_number}
                    label={PHONE_LABELS[ph.label] ?? ph.label}
                    isDefault={ph.is_default}
                    onSetDefault={() => handleSetDefaultPhone(ph.id)}
                    onRemove={() => handleRemovePhone(ph.id)}
                  />
                ))}
              </nldd-list>
            )}
            <nldd-container layout="row" gap="8" vertical-alignment="center">
              <nldd-container width="full">
                <NewValueField
                  type="tel"
                  value={newPhone}
                  onChange={(v) => { setNewPhone(v); setNewPhoneError(''); }}
                  onSubmit={handleAddPhone}
                  placeholder="+31 6 12345678"
                  accessibleLabel="Nieuw telefoonnummer"
                />
              </nldd-container>
              <Select
                aria-label="Type telefoonnummer"
                width="140px"
                value={newPhoneLabel}
                onChange={(e) => setNewPhoneLabel(e.target.value)}
                options={PHONE_LABEL_OPTIONS}
              />
              <NlddIconButton
                icon="plus"
                accessibleLabel="Telefoonnummer toevoegen"
                variant="secondary"
                disabled={!newPhone.trim() || addPhoneMutation.isPending}
                onClick={handleAddPhone}
              />
            </nldd-container>
            {newPhoneError && (
              <nldd-text size="xs" color="critical">{newPhoneError}</nldd-text>
            )}
          </nldd-container>
        )}

        {isAgent && (
          <>
            <nldd-container gap="4">
              <nldd-text size="sm" weight="medium">API Key</nldd-text>
              {displayApiKey ? (
                <>
                  <nldd-container layout="row" gap="8" vertical-alignment="center">
                    {/* The field carries its own show/hide toggle; `masked`
                        is only driven from here to reveal the key when the
                        clipboard is unavailable. */}
                    <nldd-password-field
                      readonly
                      value={displayApiKey}
                      masked={!showKey}
                      accessible-label="API key"
                      show-button-accessible-label="Toon API key"
                      hide-button-accessible-label="Verberg API key"
                    />
                    <NlddIconButton
                      icon={copied ? 'check-mark' : 'copy'}
                      accessibleLabel="Kopieer API key"
                      variant="secondary"
                      onClick={handleCopyKey}
                    />
                  </nldd-container>
                  <nldd-text size="xs" weight="bold" color="warning">
                    Deze sleutel wordt slechts eenmaal getoond. Kopieer en bewaar deze veilig.
                  </nldd-text>
                </>
              ) : editData ? (
                <nldd-container layout="row" gap="8" vertical-alignment="center">
                  {/* The stored key is never sent back, so there is nothing to
                      reveal: a disabled read-only text field shows the state,
                      where a password field would offer a toggle to nothing. */}
                  <nldd-text-field
                    readonly
                    disabled
                    value={editData.has_api_key ? '••••••••••••••••••••••••••' : 'Geen API key'}
                    accessible-label="API key"
                  />
                  {confirmRotate ? (
                    <nldd-container layout="row" gap="6" vertical-alignment="center">
                      <NlddButton
                        text="Bevestig"
                        startIcon="refresh"
                        variant="destructive"
                        size="sm"
                        loading={rotateApiKeyMutation.isPending}
                        onClick={handleRotateKey}
                      />
                      <NlddButton
                        text="Annuleer"
                        variant="neutral-transparent"
                        size="sm"
                        onClick={() => setConfirmRotate(false)}
                      />
                    </nldd-container>
                  ) : isSuperAdmin ? (
                    <NlddButton
                      text="Roteer"
                      startIcon="refresh"
                      variant="secondary"
                      size="sm"
                      onClick={handleRotateKey}
                    />
                  ) : null}
                </nldd-container>
              ) : (
                <nldd-text size="sm" color="secondary">
                  API key wordt automatisch gegenereerd na aanmaken.
                </nldd-text>
              )}
            </nldd-container>
            <RichTextFormField
              label="Beschrijving"
              value={description}
              onChange={setDescription}
              rows={3}
              placeholder="Wat doet deze agent?"
            />
          </>
        )}
        {!isAgent && (
          <CreatableSelect
            label="Functie"
            value={functie}
            onChange={setFunctie}
            options={functieOptions}
            placeholder="Selecteer of maak functie..."
            onCreate={handleCreateFunctie}
            createLabel="Nieuwe functie aanmaken"
            disabled={!!selectedPerson}
          />
        )}
        {!isAgent && (
          <CreatableSelect
            label="Expertise"
            value={expertise}
            onChange={setExpertise}
            options={[
              ...expertiseValues.map((v) => ({ value: v, label: v })),
              ...expertiseLocalAdded
                .filter((v) => !expertiseValues.includes(v))
                .map((v) => ({ value: v, label: v })),
            ]}
            placeholder="Bijv. wetgevingsjurist, BIT-adviseur..."
            onCreate={async (text) => {
              const value = text.trim();
              if (!value) return null;
              setExpertiseLocalAdded((prev) => (prev.includes(value) ? prev : [...prev, value]));
              setExpertise(value);
              return value;
            }}
            createLabel="Nieuwe expertise toevoegen"
            disabled={!!selectedPerson}
          />
        )}
        {!editData && (
          <CascadingOrgSelect
            value={orgEenheidId}
            onChange={setOrgEenheidId}
          />
        )}
        {!editData && orgEenheidId && !isAgent && (
          <nldd-form-field label="Dienstverband">
            <Select
              aria-label="Dienstverband"
              value={dienstverband}
              onChange={(e) => setDienstverband(e.target.value)}
              options={DIENSTVERBAND_OPTIONS}
            />
          </nldd-form-field>
        )}
      </nldd-container>
      </form>
      </nldd-form>
    </Modal>
  );
}
