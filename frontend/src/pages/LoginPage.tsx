import { useCallback, useRef, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { authenticateWithPasskey, getStoredPersonId, isWebAuthnCancellation } from '@/api/webauthn';
import { useNlddEvent } from '@/components/nldd/events';
import { NlddButton } from '@/components/nldd/NlddButton';
import logoImg from '/logo.png?url';

export function LoginPage() {
  const { login, refreshAuthStatus, authError, canPasskeyLogin } = useAuth();
  const [passkeyLoading, setPasskeyLoading] = useState(false);
  const [passkeyError, setPasskeyError] = useState<string | null>(null);
  const loginRef = useRef<HTMLElement>(null);

  const handlePasskeyLogin = useCallback(async () => {
    const personId = getStoredPersonId();
    if (!personId) return;

    setPasskeyLoading(true);
    setPasskeyError(null);

    try {
      const success = await authenticateWithPasskey(personId);
      if (success) {
        await refreshAuthStatus();
      } else {
        setPasskeyError('Inloggen met passkey mislukt. Probeer het opnieuw.');
      }
    } catch (err) {
      if (isWebAuthnCancellation(err)) {
        setPasskeyError(null); // User cancelled
      } else {
        setPasskeyError('Inloggen met passkey mislukt. Gebruik SSO om in te loggen.');
      }
    } finally {
      setPasskeyLoading(false);
    }
  }, [refreshAuthStatus]);

  useNlddEvent(loginRef, 'click', login);

  const errorMessage =
    passkeyError ||
    (authError ? 'Er ging iets mis bij het inloggen. Probeer het opnieuw of neem contact op met een beheerder.' : null);

  return (
    <nldd-shell background="tinted">
      <nldd-simple-section width="400px" horizontal-alignment="left" vertical-alignment="center">
        <nldd-container gap="24" horizontal-alignment="center">
          <nldd-container gap="12" horizontal-alignment="center">
            <nldd-image src={logoImg} alt="Bouwmeester" width="80" height={80} shape="circle" />
            <nldd-title size={3}>
              <h1>Bouwmeester</h1>
            </nldd-title>
            <nldd-text color="secondary" horizontal-alignment="center">
              Log in om door te gaan
            </nldd-text>
          </nldd-container>

          {errorMessage && <nldd-banner variant="critical" size="sm" text={errorMessage} />}

          {canPasskeyLogin && (
            <NlddButton
              text="Inloggen met passkey"
              startIcon="key"
              loading={passkeyLoading}
              disabled={passkeyLoading}
              onClick={handlePasskeyLogin}
              width="full"
            />
          )}

          <nldd-button
            ref={loginRef}
            text="Inloggen met SSO Rijk"
            appearance={canPasskeyLogin ? 'secondary' : 'primary'}
            width="full"
          />
        </nldd-container>
      </nldd-simple-section>
    </nldd-shell>
  );
}
