import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';
import { CurrentPersonProvider } from '@/contexts/CurrentPersonContext';
import { VocabularyProvider } from '@/contexts/VocabularyContext';
import { TaskDetailProvider } from '@/contexts/TaskDetailContext';
import { NodeDetailProvider } from '@/contexts/NodeDetailContext';
import { OpdrachtDetailProvider } from '@/contexts/OpdrachtDetailContext';
import { OpdrachtCreateProvider } from '@/contexts/OpdrachtCreateContext';
import { LeadDetailProvider } from '@/contexts/LeadDetailContext';
import { ChatProvider } from '@/contexts/ChatContext';
import { GlobalFileDropProvider } from '@/contexts/GlobalFileDropContext';
import { ToastProvider } from '@/contexts/ToastContext';
import { DetailModals } from '@/components/common/DetailModals';
import { AppLayout } from '@/components/layout/AppLayout';
import { InboxPage } from '@/pages/InboxPage';
import { CorpusPage } from '@/pages/CorpusPage';
import { NodeDetailPage } from '@/pages/NodeDetailPage';
import { TasksPage } from '@/pages/TasksPage';
import { PeoplePage } from '@/pages/PeoplePage';
import { OrganisatiePage } from '@/pages/OrganisatiePage';
import { SearchPage } from '@/pages/SearchPage';
import { ParlementairPage } from '@/pages/ParlementairPage';
import { DebattenPage } from '@/pages/DebattenPage';
import { EenheidOverzichtPage } from '@/pages/EenheidOverzichtPage';
import { OpdrachtenPage } from '@/pages/OpdrachtenPage';
import { SamenwerkingsverbandenPage } from '@/pages/SamenwerkingsverbandenPage';
import { SamenwerkingsverbandDetailPage } from '@/pages/SamenwerkingsverbandDetailPage';
import { AdminPage } from '@/pages/AdminPage';
import { AuditLogPage } from '@/pages/AuditLogPage';
import { DocsPage } from '@/pages/DocsPage';
import { InstellingenPage } from '@/pages/InstellingenPage';
import { InitiatievenPage } from '@/pages/InitiatievenPage';
import { InitiatiefPage } from '@/pages/InitiatiefPage';
import { LeadsRedirect } from '@/pages/LeadsRedirect';
import { ShareTargetPage } from '@/pages/ShareTargetPage';
import { OnboardingWizard } from '@/components/onboarding/OnboardingWizard';
import { useRef } from 'react';
import { LoginPage } from '@/pages/LoginPage';
import { AccessDeniedPage } from '@/pages/AccessDeniedPage';
import { PublicInitiatiefPage } from '@/pages/PublicInitiatiefPage';
import { ReloadPrompt } from '@/components/common/ReloadPrompt';
import { NlddButton } from '@/components/nldd/NlddButton';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

/**
 * A state that owns the whole viewport: the auth check running, or failing.
 *
 * These render OUTSIDE nldd-shell, before the shell exists, so they cannot
 * use nldd-page and have to center themselves. The height and the centering are
 * layout with nothing to inherit from; the surface colour still comes from a
 * token.
 */
function FullScreenState({ tinted, children }: { tinted?: boolean; children: React.ReactNode }) {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
        ...(tinted
          ? { backgroundColor: 'var(--semantics-surfaces-tinted-background-color)' }
          : {}),
      }}
    >
      {children}
    </div>
  );
}

function AuthGate({ children }: { children: React.ReactNode }) {
  const { loading, authenticated, oidcConfigured, error, accessDenied, deniedEmail } = useAuth();

  if (loading) {
    return (
      <FullScreenState>
        <nldd-inline-dialog variant="loading" text="Laden..." />
      </FullScreenState>
    );
  }

  // Show error state when auth status check failed
  if (error) {
    return (
      <FullScreenState tinted>
        <nldd-container max-width="400px" padding="16">
          <nldd-inline-dialog
            variant="alert"
            icon="exclamation-triangle"
            text="Verbindingsfout"
            supporting-text={error}
          >
            <NlddButton
              slot="actions"
              text="Opnieuw proberen"
              variant="primary"
              onClick={() => window.location.reload()}
            />
          </nldd-inline-dialog>
        </nldd-container>
      </FullScreenState>
    );
  }

  // If access was denied by the whitelist, show access denied page
  if (accessDenied) {
    return <AccessDeniedPage email={deniedEmail} />;
  }

  // If OIDC is configured and user is not authenticated, show login
  if (oidcConfigured && !authenticated) {
    return <LoginPage />;
  }

  // No OIDC configured (local dev) or authenticated — continue
  return <>{children}</>;
}

function OnboardingGate({ children }: { children: React.ReactNode }) {
  const { oidcConfigured, authenticated, person: authPerson } = useAuth();

  const allFeatures = (oidcConfigured && authenticated)
    ? (authPerson?.onboarding_features ?? [])
    : [];

  // Only blocking features trigger the wizard modal.
  const features = allFeatures.filter((f) => f.blocking !== false);

  // Remember the initial total so we can show "stap 2 van 3" correctly
  // even after earlier steps have been completed.
  const totalRef = useRef(0);
  if (features.length > totalRef.current) {
    totalRef.current = features.length;
  }
  const stepNumber = totalRef.current - features.length + 1;

  if (features.length === 0) {
    totalRef.current = 0;
    return <>{children}</>;
  }

  return <OnboardingWizard features={features} stepNumber={stepNumber} totalSteps={totalRef.current} />;
}

function AuthenticatedApp() {
  return (
    <AuthProvider>
      <AuthGate>
        <OnboardingGate>
        <CurrentPersonProvider>
          <VocabularyProvider>
          <GlobalFileDropProvider>
            <ChatProvider>
            <TaskDetailProvider>
            <NodeDetailProvider>
            <OpdrachtCreateProvider>
            <OpdrachtDetailProvider>
            <LeadDetailProvider>
              <Routes>
                <Route element={<AppLayout />}>
                  <Route path="/" element={<InboxPage />} />
                  <Route path="/corpus" element={<CorpusPage />} />
                  <Route path="/nodes/:id" element={<NodeDetailPage />} />
                  <Route path="/tasks" element={<TasksPage />} />
                  <Route path="/people" element={<PeoplePage />} />
                  <Route path="/organisatie" element={<OrganisatiePage />} />
                  <Route path="/eenheid-overzicht" element={<EenheidOverzichtPage />} />
                  <Route path="/search" element={<SearchPage />} />
                  <Route path="/parlementair" element={<ParlementairPage />} />
                  <Route path="/debatten" element={<DebattenPage />} />
                  <Route path="/opdrachten" element={<OpdrachtenPage />} />
                  <Route path="/samenwerkingsverbanden" element={<SamenwerkingsverbandenPage />} />
                  <Route path="/samenwerkingsverbanden/:id" element={<SamenwerkingsverbandDetailPage />} />
                  <Route path="/admin" element={<AdminPage />} />
                  <Route path="/auditlog" element={<AuditLogPage />} />
                  <Route path="/docs" element={<DocsPage />} />
                  <Route path="/instellingen" element={<InstellingenPage />} />
                  <Route path="/initiatieven" element={<InitiatievenPage />} />
                  <Route path="/initiatieven/:id/:tab?" element={<InitiatiefPage />} />
                  <Route path="/leads" element={<LeadsRedirect />} />
                  <Route path="/share-target" element={<ShareTargetPage />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
              </Routes>
              <DetailModals />
            </LeadDetailProvider>
            </OpdrachtDetailProvider>
            </OpdrachtCreateProvider>
            </NodeDetailProvider>
            </TaskDetailProvider>
          </ChatProvider>
          </GlobalFileDropProvider>
          </VocabularyProvider>
        </CurrentPersonProvider>
        </OnboardingGate>
      </AuthGate>
    </AuthProvider>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ReloadPrompt />
        <BrowserRouter>
          <Routes>
            <Route path="/c/:slug" element={<PublicInitiatiefPage />} />
            <Route path="*" element={<AuthenticatedApp />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
