import { useRef, useState } from 'react';
import { useWhitelist, useAddWhitelistEmail, useRemoveWhitelistEmail } from '@/hooks/useAdmin';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';

export function WhitelistManager() {
  const { data: emails, isLoading } = useWhitelist();
  const addEmail = useAddWhitelistEmail();
  const removeEmail = useRemoveWhitelistEmail();
  const [newEmail, setNewEmail] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const emailFieldRef = useRef<HTMLElement>(null);

  useNlddEvent(emailFieldRef, 'input', (e) => setNewEmail(eventValue(e)));

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newEmail.trim();
    if (!trimmed) return;
    addEmail.mutate(trimmed, {
      onSuccess: () => setNewEmail(''),
    });
  };

  const handleDelete = (id: string) => {
    removeEmail.mutate(id, {
      onSuccess: () => setConfirmDeleteId(null),
    });
  };

  if (isLoading) {
    return <LoadingSpinner padding="32" />;
  }

  return (
    <nldd-container gap="16">
      {/* Add form */}
      <nldd-form>
      <form onSubmit={handleAdd}>
        <nldd-container layout="row" gap="8">
          <nldd-container width="fit-content" className="row-fill">
            <nldd-text-field
              ref={emailFieldRef}
              type="email"
              value={newEmail}
              placeholder="E-mailadres toevoegen..."
              accessible-label="E-mailadres toevoegen"
              autocomplete="email"
              required
            />
          </nldd-container>
          <NlddButton
            type="submit"
            text="Toevoegen"
            startIcon="plus"
            disabled={addEmail.isPending || !newEmail.trim()}
          />
        </nldd-container>
      </form>
      </nldd-form>

      {/* Email list */}
      <nldd-table
        columns="minmax(200px,1fr) 160px 120px 48px"
        sm-columns="1fr 48px"
        accessible-label="Toegangslijst e-mailadressen"
      >
        <nldd-table-row slot="header">
          <nldd-text-cell text="E-mailadres" />
          <nldd-text-cell text="Toegevoegd door" hide-below="md" />
          <nldd-text-cell text="Datum" hide-below="md" />
          <nldd-text-cell />
        </nldd-table-row>
        {emails?.map((entry) => (
          <nldd-table-row key={entry.id}>
            <nldd-text-cell text={entry.email} />
            <nldd-text-cell text={entry.added_by || '-'} color="secondary" hide-below="md" />
            <nldd-text-cell
              text={new Date(entry.created_at).toLocaleDateString('nl-NL')}
              color="secondary"
              hide-below="md"
            />
            <nldd-cell>
              {confirmDeleteId === entry.id ? (
                <nldd-container layout="row" gap="4" vertical-alignment="center">
                  <NlddButton
                    text="Ja"
                    variant="destructive"
                    size="xs"
                    disabled={removeEmail.isPending}
                    onClick={() => handleDelete(entry.id)}
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
                  onClick={() => setConfirmDeleteId(entry.id)}
                />
              )}
            </nldd-cell>
          </nldd-table-row>
        ))}
        <div slot="empty">
          <EmptyState icon="inbox" title="Geen e-mailadressen op de toegangslijst" />
        </div>
      </nldd-table>

      <nldd-text size="xs" color="secondary">
        <p>
          Alleen personen met een e-mailadres op deze lijst kunnen inloggen. Wanneer de lijst leeg is,
          is alle toegang open (lokale ontwikkeling).
        </p>
      </nldd-text>
    </nldd-container>
  );
}
