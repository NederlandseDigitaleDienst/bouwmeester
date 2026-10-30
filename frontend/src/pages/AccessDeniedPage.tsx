import { useState, useEffect, useCallback, useRef } from 'react';
import { BASE_URL, getCsrfToken } from '@/api/client';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { NlddButton } from '@/components/nldd/NlddButton';
import logoImg from '/logo.png?url';

interface AccessDeniedPageProps {
  email: string | null;
}

type RequestState =
  | { step: 'idle' }
  | { step: 'form' }
  | { step: 'submitting' }
  | { step: 'pending' }
  | { step: 'approved' }
  | { step: 'denied'; reason?: string }
  | { step: 'error'; message: string }
  | { step: 'already_pending' };

export function AccessDeniedPage({ email }: AccessDeniedPageProps) {
  const [state, setState] = useState<RequestState>({ step: 'idle' });

  const handleLogout = () => {
    window.location.href = `${BASE_URL}/api/auth/logout`;
  };

  // Check for existing pending request on mount
  useEffect(() => {
    if (!email) return;
    fetch(`${BASE_URL}/api/auth/access-request-status?email=${encodeURIComponent(email)}`, {
      credentials: 'include',
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.status === 'pending') {
          setState({ step: 'pending' });
        } else if (data.status === 'denied') {
          setState({ step: 'denied', reason: data.deny_reason });
        } else if (data.status === 'approved') {
          setState({ step: 'approved' });
        }
      })
      .catch(() => {
        // Ignore — stay on idle
      });
  }, [email]);

  // Poll for status changes while pending
  useEffect(() => {
    if (state.step !== 'pending' || !email) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(
          `${BASE_URL}/api/auth/access-request-status?email=${encodeURIComponent(email)}`,
          { credentials: 'include' }
        );
        const data = await res.json();
        if (data.status === 'approved') {
          setState({ step: 'approved' });
        } else if (data.status === 'denied') {
          setState({ step: 'denied', reason: data.deny_reason });
        }
      } catch {
        // Ignore polling errors
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [state.step, email]);

  // Auto-reload when approved
  useEffect(() => {
    if (state.step === 'approved') {
      const timer = setTimeout(() => window.location.reload(), 1500);
      return () => clearTimeout(timer);
    }
  }, [state.step]);

  const handleSubmit = useCallback(
    async (naam: string) => {
      if (!email) return;

      setState({ step: 'submitting' });
      try {
        const res = await fetch(`${BASE_URL}/api/auth/request-access`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': getCsrfToken(),
          },
          credentials: 'include',
          body: JSON.stringify({ email, naam }),
        });

        if (!res.ok) {
          if (res.status === 429) {
            setState({ step: 'error', message: 'Te veel verzoeken, probeer het later opnieuw.' });
            return;
          }
          setState({ step: 'error', message: 'Er ging iets mis. Probeer het later opnieuw.' });
          return;
        }

        const data = await res.json();
        if (data.status === 'already_allowed') {
          setState({ step: 'approved' });
        } else if (data.status === 'already_pending') {
          setState({ step: 'already_pending' });
        } else {
          setState({ step: 'pending' });
        }
      } catch {
        setState({ step: 'error', message: 'Verbindingsfout. Probeer het later opnieuw.' });
      }
    },
    [email]
  );

  return (
    <nldd-shell background="tinted">
      {/* One alignment for the whole card. The section was set to `left` while
          the container inside it was `center`, so the logo and the title were
          centred and everything below them was not. */}
      <nldd-simple-section width="480px" horizontal-alignment="center" vertical-alignment="center">
        <nldd-container gap="24" horizontal-alignment="center">
          <nldd-container gap="12" horizontal-alignment="center">
            <nldd-image src={logoImg} alt="Bouwmeester" width="80" height={80} shape="circle" />
            <nldd-title size={3}>
              <h1>Bouwmeester</h1>
            </nldd-title>
          </nldd-container>

          {/* The alignment is set, not derived. Left to itself the element
              reads content in its default slot as a task and aligns left,
              which put this message out of step with the title above it. */}
          <nldd-inline-dialog
            variant="alert"
            horizontal-alignment="center"
            text="Geen toegang"
            {...(email ? { 'supporting-text': `Ingelogd als ${email}` } : {})}
          >
            <nldd-container gap="16" horizontal-alignment="center" padding-top="16">
              {state.step === 'idle' && (
                <>
                  <nldd-text color="secondary">
                    Je account staat niet op de toegangslijst voor deze applicatie.
                  </nldd-text>
                  <NlddButton
                    text="Toegang aanvragen"
                    width="full"
                    onClick={() => setState({ step: 'form' })}
                  />
                </>
              )}

              {state.step === 'form' && <AccessRequestForm onSubmit={handleSubmit} />}

              {state.step === 'submitting' && (
                <nldd-text color="secondary">Verzoek wordt verstuurd...</nldd-text>
              )}

              {(state.step === 'pending' || state.step === 'already_pending') && (
                <nldd-banner
                  variant="warning"
                  size="sm"
                  text="Je verzoek is verstuurd."
                  supporting-text="Een beheerder zal je verzoek beoordelen. Wachten op goedkeuring..."
                />
              )}

              {state.step === 'approved' && (
                <nldd-banner
                  variant="success"
                  size="sm"
                  text="Je toegang is goedgekeurd!"
                  supporting-text="Pagina wordt herladen..."
                />
              )}

              {state.step === 'denied' && (
                <>
                  <nldd-banner
                    variant="critical"
                    size="sm"
                    text="Je verzoek is afgewezen."
                    {...(state.reason ? { 'supporting-text': `Reden: ${state.reason}` } : {})}
                  />
                  <NlddButton
                    text="Opnieuw aanvragen"
                    width="full"
                    onClick={() => setState({ step: 'form' })}
                  />
                </>
              )}

              {state.step === 'error' && (
                <>
                  <nldd-text color="critical">{state.message}</nldd-text>
                  <NlddButton
                    text="Opnieuw proberen"
                    variant="neutral-transparent"
                    onClick={() => setState({ step: 'idle' })}
                  />
                </>
              )}
            </nldd-container>
          </nldd-inline-dialog>

          <NlddButton
            text="Uitloggen en opnieuw proberen"
            variant="secondary"
            width="full"
            onClick={handleLogout}
          />
        </nldd-container>
      </nldd-simple-section>
    </nldd-shell>
  );
}

/**
 * The name form lives in its own component so its field mounts together with
 * the hook that listens to it. `useNlddEvent` attaches in an effect that only
 * reruns when its deps change; with the field rendered conditionally inside the
 * page, that effect ran while the ref was still null (the idle step) and never
 * again, so typing never reached state and the submit button stayed disabled.
 */
function AccessRequestForm({ onSubmit }: { onSubmit: (naam: string) => void }) {
  const [naam, setNaam] = useState('');
  const naamFieldRef = useRef<HTMLElement>(null);

  useNlddEvent(naamFieldRef, 'input', (e) => setNaam(eventValue(e)));

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = naam.trim();
    if (trimmed) onSubmit(trimmed);
  };

  return (
    // nldd-form sets container-type: inline-size, so in the centered parent it
    // would shrink to nothing; the full-width container gives it a width.
    <nldd-container>
      <nldd-form>
      <form onSubmit={handleSubmit}>
      <nldd-container gap="12">
        <nldd-form-field label="Je volledige naam">
          <nldd-text-field
            ref={naamFieldRef}
            value={naam}
            placeholder="Je volledige naam"
            autocomplete="name"
            required
            width="full"
          />
        </nldd-form-field>
        <NlddButton type="submit" text="Verzoek versturen" width="full" disabled={!naam.trim()} />
      </nldd-container>
      </form>
      </nldd-form>
    </nldd-container>
  );
}
