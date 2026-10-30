import { useCallback, useState, useEffect } from 'react';
import { Modal } from '@/components/common/Modal';
import { Input } from '@/components/common/Input';
import { useCreatePerson } from '@/hooks/usePeople';
import { checkDuplicates } from '@/api/people';
import type { DuplicateCheckHit } from '@/api/people';
import { useDebounce } from '@/hooks/useDebounce';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddListItemButton } from '@/components/nldd/NlddLink';

interface DuplicateRowProps {
  hit: DuplicateCheckHit;
  onSelect: (id: string) => void;
}

function DuplicateRow({ hit, onSelect }: DuplicateRowProps) {
  const handleClick = useCallback(() => onSelect(hit.id), [hit.id, onSelect]);

  const supporting = [hit.email, hit.functie].filter(Boolean).join(' — ');

  return (
    <NlddListItemButton onClick={handleClick}>
      <nldd-text-cell text={hit.naam} {...(supporting ? { 'supporting-text': supporting } : {})} />
      <nldd-text-cell text="Selecteer" color="accent" horizontal-alignment="right" width="fit-content" />
    </NlddListItemButton>
  );
}

interface PersonQuickCreateFormProps {
  open: boolean;
  onClose: () => void;
  initialName: string;
  onCreated: (personId: string) => void;
}

export function PersonQuickCreateForm({
  open,
  onClose,
  initialName,
  onCreated,
}: PersonQuickCreateFormProps) {
  const [naam, setNaam] = useState(initialName);
  const [email, setEmail] = useState('');
  const [duplicates, setDuplicates] = useState<DuplicateCheckHit[]>([]);
  const [searching, setSearching] = useState(false);
  const createPerson = useCreatePerson();

  const debouncedNaam = useDebounce(naam.trim(), 400);

  useEffect(() => {
    if (open) {
      setNaam(initialName);
      setEmail('');
      setDuplicates([]);
    }
  }, [open, initialName]);

  // Check for duplicates using the same algorithm as the backend create guard
  useEffect(() => {
    if (!debouncedNaam || debouncedNaam.length < 2) {
      setDuplicates([]);
      return;
    }
    let cancelled = false;
    setSearching(true);
    checkDuplicates(debouncedNaam)
      .then((results) => {
        if (!cancelled) {
          setDuplicates(results);
          setSearching(false);
        }
      })
      .catch(() => {
        if (!cancelled) setSearching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedNaam]);

  const doCreate = async (force: boolean) => {
    if (!naam.trim()) return;
    try {
      const person = await createPerson.mutateAsync({
        naam: naam.trim(),
        email: email.trim() || undefined,
        force,
      });
      onCreated(person.id);
      setNaam('');
      setEmail('');
      onClose();
    } catch {
      // Error toast already shown by useMutationWithError
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // If duplicates are shown, Enter should not bypass the warning — the user
    // must explicitly click "Toch aanmaken" or select an existing person.
    if (duplicates.length > 0) return;
    doCreate(false);
  };

  const handleSelectExisting = (personId: string) => {
    onCreated(personId);
    setNaam('');
    setEmail('');
    onClose();
  };

  const hasDuplicates = duplicates.length > 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Persoon snel aanmaken"
      size="sm"
      footer={
        <>
          <NlddButton variant="secondary" onClick={onClose} text="Annuleren" />
          {hasDuplicates ? (
            <NlddButton
              onClick={() => doCreate(true)}
              loading={createPerson.isPending}
              disabled={!naam.trim()}
              variant="secondary"
              text="Toch aanmaken"
            />
          ) : (
            <NlddButton
              onClick={() => doCreate(false)}
              loading={createPerson.isPending}
              disabled={!naam.trim()}
              text="Aanmaken"
            />
          )}
        </>
      }
    >
      {/*
        Submit/cancel live in Modal's `footer`, a sibling of `children`, not
        a descendant of nldd-form, so nldd-form-actions cannot reach them
        from here. Wrapping the body still gets autofill and label-alignment
        inheritance for the fields.
      */}
      <nldd-form>
      <form onSubmit={handleSubmit}>
        <nldd-container gap="16">
          <Input
            label="Naam"
            value={naam}
            onChange={(e) => setNaam(e.target.value)}
            placeholder="Volledige naam"
            autoComplete="name"
            required
            autoFocus
          />
          <Input
            label="E-mail"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email@voorbeeld.nl"
            autoComplete="email"
          />

          {searching && (
            <nldd-inline-dialog variant="loading" text="Zoeken naar bestaande personen..." size="md" />
          )}

          {hasDuplicates && !searching && (
            <nldd-container gap="8">
              <nldd-inline-dialog
                variant="alert"
                text="Er bestaan al personen met een vergelijkbare naam"
                supporting-text="Kies een bestaande persoon, of maak toch een nieuwe aan."
              />
              <nldd-list appearance="box-tinted" accessible-label="Vergelijkbare personen">
                {duplicates.map((d) => (
                  <DuplicateRow key={d.id} hit={d} onSelect={handleSelectExisting} />
                ))}
              </nldd-list>
            </nldd-container>
          )}
        </nldd-container>
      </form>
      </nldd-form>
    </Modal>
  );
}
