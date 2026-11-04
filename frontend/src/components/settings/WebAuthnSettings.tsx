import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import {
  listCredentials,
  deleteCredential,
  registerCredential,
  isWebAuthnAvailable,
  isWebAuthnCancellation,
  clearStoredPersonId,
  setStoredPersonId,
} from '@/api/webauthn';
import { useAuth } from '@/contexts/AuthContext';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { Icon } from '@/components/nldd/Icon';

export function WebAuthnSettings() {
  const { person } = useAuth();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [deleteCredId, setDeleteCredId] = useState<string | null>(null);

  const { data: credentials, isLoading, isError: queryError } = useQuery({
    queryKey: ['webauthn-credentials'],
    queryFn: listCredentials,
  });

  const registerMutation = useMutation({
    mutationFn: () => registerCredential('Passkey'),
    onSuccess: () => {
      setError(null);
      setSuccess('Passkey is toegevoegd');
      // Store person_id in localStorage for passkey login.
      if (person?.id) {
        setStoredPersonId(person.id);
      }
      queryClient.invalidateQueries({ queryKey: ['webauthn-credentials'] });
      setTimeout(() => setSuccess(null), 3000);
    },
    onError: (err: Error) => {
      setSuccess(null);
      if (isWebAuthnCancellation(err)) {
        setError('Registratie geannuleerd');
      } else {
        setError('Registratie mislukt. Probeer het opnieuw.');
      }
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteCredential,
    onSuccess: (_data, deletedId) => {
      // If we just deleted the last credential, clear the stored person ID
      // so the passkey login button no longer appears on the login page.
      if (credentials && credentials.length === 1 && credentials[0].id === deletedId) {
        clearStoredPersonId();
      }
      queryClient.invalidateQueries({ queryKey: ['webauthn-credentials'] });
    },
  });

  if (!isWebAuthnAvailable()) {
    return (
      <nldd-card>
        <nldd-container padding="24" gap="4">
          <nldd-text weight="medium">Passkeys</nldd-text>
          <nldd-text size="sm" color="secondary">
            Je browser ondersteunt geen passkeys (WebAuthn). Gebruik een moderne browser om deze
            functie te gebruiken.
          </nldd-text>
        </nldd-container>
      </nldd-card>
    );
  }

  return (
    <nldd-card>
      <nldd-container padding="24" gap="16">
        <nldd-container layout="row" gap="12" vertical-alignment="center">
          <Icon name="key" size="lg" />
          <nldd-container gap="2">
            <nldd-text weight="medium">Passkeys</nldd-text>
            <nldd-text size="sm" color="secondary">
              Log snel opnieuw in met een passkey. Je ontgrendelt hem met Face ID, je vingerafdruk, je pincode of een beveiligingssleutel.
            </nldd-text>
          </nldd-container>
        </nldd-container>

        <nldd-container gap="12">
          {error && <nldd-banner variant="critical" size="sm" text={error} />}
          {success && <nldd-banner variant="success" size="sm" text={success} />}
          {queryError && (
            <nldd-banner
              variant="critical"
              size="sm"
              text="Credentials konden niet worden opgehaald. Probeer de pagina te vernieuwen."
            />
          )}

          {isLoading ? (
            <nldd-activity-indicator size="20" show-text text="Laden..." />
          ) : (
            <>
              {credentials && credentials.length > 0 && (
                <nldd-list appearance="box-tinted" dividers="always" accessible-label="Passkeys">
                  {credentials.map((cred) => (
                    <nldd-list-item key={cred.id}>
                      <nldd-icon-cell icon="key" size="20" />
                      <nldd-text-cell
                        text={cred.label}
                        supporting-text={
                          `Geregistreerd ${new Date(cred.created_at).toLocaleDateString('nl-NL')}` +
                          (cred.last_used_at
                            ? ` · Laatst gebruikt ${new Date(cred.last_used_at).toLocaleDateString('nl-NL')}`
                            : '')
                        }
                      />
                      <nldd-cell horizontal-alignment="right">
                        <NlddIconButton
                          icon="trash"
                          accessibleLabel="Verwijderen"
                          variant="critical-transparent"
                          size="sm"
                          disabled={deleteMutation.isPending}
                          onClick={() => setDeleteCredId(cred.id)}
                        />
                      </nldd-cell>
                    </nldd-list-item>
                  ))}
                </nldd-list>
              )}

              <NlddButton
                text="Passkey toevoegen"
                startIcon="plus"
                loading={registerMutation.isPending}
                disabled={registerMutation.isPending}
                onClick={() => registerMutation.mutate()}
              />
            </>
          )}
        </nldd-container>
      </nldd-container>
      <ConfirmDialog
        open={!!deleteCredId}
        onClose={() => setDeleteCredId(null)}
        onConfirm={() => {
          if (deleteCredId) {
            deleteMutation.mutate(deleteCredId);
            setDeleteCredId(null);
          }
        }}
        title="Passkey verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
      >
        Weet je zeker dat je deze passkey wilt verwijderen?
      </ConfirmDialog>
    </nldd-card>
  );
}
