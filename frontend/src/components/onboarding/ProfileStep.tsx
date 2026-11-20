import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiPost, ApiError } from '@/api/client';
import { useAuth } from '@/contexts/AuthContext';
import { CascadingOrgSelect } from '@/components/common/CascadingOrgSelect';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { addPersonEmail, addPersonPhone } from '@/api/people';
import { FUNCTIE_LABELS, PHONE_LABELS } from '@/types';
import type { Person } from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { Select } from '@/components/common/Select';

const EXCLUDED_ONBOARDING_FUNCTIES = new Set([
  'minister',
  'staatssecretaris',
  'secretaris_generaal',
  'plaatsvervangend_secretaris_generaal',
]);

const DEFAULT_FUNCTIE_OPTIONS: SelectOption[] = Object.entries(FUNCTIE_LABELS)
  .filter(([value]) => !EXCLUDED_ONBOARDING_FUNCTIES.has(value))
  .map(([value, label]) => ({ value, label }));

const PHONE_LABEL_OPTIONS = Object.entries(PHONE_LABELS).map(
  ([value, label]) => ({ value, label }),
);

interface OnboardingPayload {
  naam: string;
  functie: string;
  organisatie_eenheid_id: string;
}

interface ExtraEmail {
  email: string;
}

interface ExtraPhone {
  phone_number: string;
  label: string;
}

/** One row of the extra-emails list; owns its own ref so useNlddEvent can bind
 *  per row instead of every row sharing one ref from a .map(). */
function EmailRow({
  email,
  onChange,
  onRemove,
}: {
  email: string;
  onChange: (value: string) => void;
  onRemove: () => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', (e) => onChange(eventValue(e)));

  return (
    <nldd-container layout="row" gap="8" vertical-alignment="center">
      <nldd-text-field ref={ref} type="email" value={email} placeholder="E-mailadres" autocomplete="email" width="full" />
      <NlddIconButton
        icon="close"
        accessibleLabel="E-mailadres verwijderen"
        variant="neutral-transparent"
        size="sm"
        onClick={onRemove}
      />
    </nldd-container>
  );
}

/** One row of the extra-phones list; same per-row ref reasoning as EmailRow. */
function PhoneRow({
  phone,
  onChangeNumber,
  onChangeLabel,
  onRemove,
}: {
  phone: ExtraPhone;
  onChangeNumber: (value: string) => void;
  onChangeLabel: (value: string) => void;
  onRemove: () => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', (e) => onChangeNumber(eventValue(e)));

  return (
    <nldd-container layout="row" gap="8" vertical-alignment="center">
      <nldd-text-field ref={ref} type="tel" value={phone.phone_number} placeholder="Telefoonnummer" autocomplete="tel" width="full" />
      <Select
        value={phone.label}
        aria-label="Soort telefoonnummer"
        onChange={(e) => onChangeLabel(e.target.value)}
        options={PHONE_LABEL_OPTIONS}
      />
      <NlddIconButton
        icon="close"
        accessibleLabel="Telefoonnummer verwijderen"
        variant="neutral-transparent"
        size="sm"
        onClick={onRemove}
      />
    </nldd-container>
  );
}

export function ProfileStep({ onComplete }: { onComplete: () => void }) {
  const { person } = useAuth();
  const queryClient = useQueryClient();

  const [naam, setNaam] = useState(person?.name ?? '');
  const [functie, setFunctie] = useState('');
  const [functieOptions, setFunctieOptions] = useState<SelectOption[]>(DEFAULT_FUNCTIE_OPTIONS);
  const [orgId, setOrgId] = useState('');
  const [extraEmails, setExtraEmails] = useState<ExtraEmail[]>([]);
  const [extraPhones, setExtraPhones] = useState<ExtraPhone[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const naamFieldRef = useRef<HTMLElement>(null);

  const mutation = useMutation({
    mutationFn: async (data: OnboardingPayload) => {
      const result = await apiPost<Person>('/api/auth/onboarding', data);
      const personId = result.id;
      const promises: Promise<unknown>[] = [];
      for (const e of extraEmails) {
        if (e.email.trim()) {
          promises.push(addPersonEmail(personId, { email: e.email.trim() }));
        }
      }
      for (const p of extraPhones) {
        if (p.phone_number.trim()) {
          promises.push(addPersonPhone(personId, { phone_number: p.phone_number.trim(), label: p.label }));
        }
      }
      const results = await Promise.allSettled(promises);
      const failed = results.filter((r) => r.status === 'rejected');
      const warningMessages = failed.map((r) => {
        const reason = (r as PromiseRejectedResult).reason;
        if (reason instanceof ApiError && reason.body && typeof reason.body === 'object' && 'detail' in reason.body) {
          return String((reason.body as { detail: string }).detail);
        }
        return 'Kon contactgegeven niet opslaan';
      });
      if (warningMessages.length > 0) {
        setWarnings(warningMessages);
      }
      return { result, hasWarnings: warningMessages.length > 0 };
    },
    onSuccess: async ({ hasWarnings }) => {
      await queryClient.invalidateQueries({ queryKey: ['people'] });
      // The profile itself was saved (naam + functie + placement request).
      // Hold the wizard open so the user sees which extras failed; they
      // can click Doorgaan to continue.
      if (!hasWarnings) {
        await onComplete();
      }
    },
    onError: (err) => {
      if (err instanceof ApiError && err.body && typeof err.body === 'object' && 'detail' in err.body) {
        setError(String((err.body as { detail: string }).detail));
      } else {
        setError('Er is iets misgegaan. Probeer het opnieuw.');
      }
    },
  });

  const handleCreateFunctie = async (text: string): Promise<string | null> => {
    const value = text.toLowerCase().replace(/\s+/g, '_');
    setFunctieOptions((prev) => [...prev, { value, label: text }]);
    setFunctie(value);
    return value;
  };

  const canSubmit = naam.trim().length > 0 && functie.trim().length > 0 && orgId.length > 0;

  const handleSubmit = () => {
    if (!canSubmit) return;
    setError(null);
    mutation.mutate({
      naam: naam.trim(),
      functie: functie.trim(),
      organisatie_eenheid_id: orgId,
    });
  };

  useNlddEvent(naamFieldRef, 'input', (e) => setNaam(eventValue(e)));

  return (
    <nldd-container gap="16">
      <nldd-text size="sm" color="secondary">
        <p>Vul je profiel aan om aan de slag te gaan.</p>
      </nldd-text>

      <nldd-container gap="16">
        <nldd-form-field label="Naam">
          <nldd-text-field ref={naamFieldRef} value={naam} placeholder="Volledige naam" autocomplete="name" width="full" />
        </nldd-form-field>

        <CreatableSelect
          label="Functie"
          value={functie}
          onChange={setFunctie}
          options={functieOptions}
          placeholder="Typ om functie te zoeken of aan te maken..."
          onCreate={handleCreateFunctie}
          createLabel="Nieuwe functie aanmaken"
        />

        <CascadingOrgSelect value={orgId} onChange={setOrgId} minDepth={2} />

        {/* Extra email addresses */}
        <nldd-form-field
          label="Extra e-mailadressen"
          {...(person?.email ? { 'supporting-label': `${person.email} wordt automatisch toegevoegd.` } : {})}
        >
          <nldd-container gap="8">
            {extraEmails.map((entry, i) => (
              <EmailRow
                key={i}
                email={entry.email}
                onChange={(value) => {
                  const updated = [...extraEmails];
                  updated[i] = { email: value };
                  setExtraEmails(updated);
                }}
                onRemove={() => setExtraEmails(extraEmails.filter((_, j) => j !== i))}
              />
            ))}
            <NlddButton
              text="E-mailadres toevoegen"
              startIcon="plus"
              variant="neutral-transparent"
              size="sm"
              onClick={() => setExtraEmails([...extraEmails, { email: '' }])}
            />
          </nldd-container>
        </nldd-form-field>

        {/* Phone numbers */}
        <nldd-form-field label="Telefoonnummers" optional>
          <nldd-container gap="8">
            {extraPhones.map((entry, i) => (
              <PhoneRow
                key={i}
                phone={entry}
                onChangeNumber={(value) => {
                  const updated = [...extraPhones];
                  updated[i] = { ...updated[i], phone_number: value };
                  setExtraPhones(updated);
                }}
                onChangeLabel={(value) => {
                  const updated = [...extraPhones];
                  updated[i] = { ...updated[i], label: value };
                  setExtraPhones(updated);
                }}
                onRemove={() => setExtraPhones(extraPhones.filter((_, j) => j !== i))}
              />
            ))}
            <NlddButton
              text="Telefoonnummer toevoegen"
              startIcon="plus"
              variant="neutral-transparent"
              size="sm"
              onClick={() => setExtraPhones([...extraPhones, { phone_number: '', label: 'werk' }])}
            />
          </nldd-container>
        </nldd-form-field>

        {error && <nldd-banner variant="critical" size="sm" text={error} />}
        {warnings.length > 0 && (
          <nldd-banner variant="warning" size="sm" text="Je profiel is opgeslagen, maar niet alle contactgegevens konden worden toegevoegd:">
            <nldd-container gap="4">
              {warnings.map((w, i) => (
                <nldd-text key={i} size="sm">
                  <p>
                    - {w}
                  </p>
                </nldd-text>
              ))}
              <nldd-text size="xs" color="secondary">
                <p>Je kunt deze later toevoegen via Instellingen.</p>
              </nldd-text>
            </nldd-container>
          </nldd-banner>
        )}

        <nldd-container horizontal-alignment="right">
          {warnings.length > 0 ? (
            <NlddButton text="Doorgaan" onClick={onComplete} />
          ) : (
            <NlddButton
              text={mutation.isPending ? 'Bezig...' : 'Profiel voltooien'}
              disabled={!canSubmit}
              loading={mutation.isPending}
              onClick={handleSubmit}
            />
          )}
        </nldd-container>
      </nldd-container>
    </nldd-container>
  );
}
