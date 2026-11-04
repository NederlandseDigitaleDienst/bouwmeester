import { useEffect, useRef, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { ChatToggleButton } from '@/components/chat/ChatToggleButton';
import { SearchModal } from '@/components/search/SearchModal';
import { useUIStore } from '@/store/ui';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { useAuth } from '@/contexts/AuthContext';
import { OnboardingModal } from '@/components/onboarding/OnboardingModal';
import { GlobalDropOverlay } from '@/components/common/GlobalDropOverlay';
import { FileActionChooser } from '@/components/common/FileActionChooser';
import { useGlobalFileDropContext } from '@/hooks/useGlobalFileDropContext';
import { orUndef } from '@/components/nldd/events';
import { NlddButton } from '@/components/nldd/NlddButton';

/** The subset of nldd-navigation-split-view's imperative API we drive. */
type SplitViewElement = HTMLElement & {
  showPrimarySidebarSheet?: () => Promise<void>;
  hidePrimarySidebarSheet?: () => void;
};

function PlacementBanner() {
  const { person } = useAuth();
  const [showReRequest, setShowReRequest] = useState(false);

  if (!person?.needs_placement) return null;

  // User's last request was denied — show re-request option
  if (person.placement_denied) {
    return (
      <>
        <nldd-banner variant="critical" size="sm" text="Je teamverzoek is afgewezen.">
          <div slot="actions">
            <NlddButton
              text="Opnieuw aanvragen"
              variant="critical-tinted"
              size="sm"
              onClick={() => setShowReRequest(true)}
            />
          </div>
        </nldd-banner>
        {showReRequest && <OnboardingModal />}
      </>
    );
  }

  // User has a pending request
  if (person.has_pending_placement) {
    return (
      <nldd-banner
        variant="warning"
        size="sm"
        text="Je teamverzoek wordt beoordeeld door een manager."
      />
    );
  }

  return null;
}

export function AppLayout() {
  const isMobile = useIsMobile();
  const location = useLocation();
  const {
    mobileSidebarOpen,
    setMobileSidebarOpen,
    sidebarOpen,
    chatOpen,
    searchModalOpen,
    setSearchModalOpen,
  } = useUIStore();
  const { isDragging } = useGlobalFileDropContext();
  const splitViewRef = useRef<HTMLElement>(null);

  // The split view owns the sidebar sheet on narrow screens. Mirror our store
  // onto it rather than rendering a second overlay of our own: it handles the
  // backdrop, the focus trap and Escape itself.
  useEffect(() => {
    const el = splitViewRef.current as SplitViewElement | null;
    if (!el || !isMobile) return;
    if (mobileSidebarOpen) void el.showPrimarySidebarSheet?.();
    else el.hidePrimarySidebarSheet?.();
  }, [mobileSidebarOpen, isMobile]);

  // The split view closes the sheet itself on Escape or a backdrop click and
  // dispatches nothing, so the store would stay stuck on "open" and the next
  // toggle would appear dead. Watch the underlying <dialog> instead.
  useEffect(() => {
    const el = splitViewRef.current as SplitViewElement | null;
    if (!el || !isMobile || !mobileSidebarOpen) return;

    const dialog = el.shadowRoot?.querySelector('dialog');
    if (!dialog) return;

    const onClose = () => setMobileSidebarOpen(false);
    dialog.addEventListener('close', onClose);
    return () => dialog.removeEventListener('close', onClose);
  }, [isMobile, mobileSidebarOpen, setMobileSidebarOpen]);

  // Global "/" shortcut to open search modal (unless on /search page)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.key === '/' &&
        !e.ctrlKey &&
        !e.metaKey &&
        !e.altKey &&
        !(document.activeElement instanceof HTMLInputElement) &&
        !(document.activeElement instanceof HTMLTextAreaElement) &&
        !(document.activeElement as HTMLElement)?.isContentEditable
      ) {
        // On /search page, the page handles "/" itself (focuses input)
        if (location.pathname === '/search') return;
        e.preventDefault();
        setSearchModalOpen(true);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [location.pathname, setSearchModalOpen]);

  return (
    <>
      <nldd-skip-link href="#main-content" text="Direct naar de inhoud" />
      <nldd-shell background="tinted">
        <nldd-navigation-split-view
          ref={splitViewRef}
          primary-sidebar-accessible-label="Navigatie"
          inspector-accessible-label="Assistent"
          /* Below lg the split view moves the sidebar into a sheet itself, so
             this layout needs no overlay of its own. */
          primary-sidebar-as-sheet={orUndef(isMobile)}
          /* The width of the sidebar column lives on the split view, not on the
             pane. Its shadow DOM wraps the pane in a div whose width is entirely
             `min-width: var(--_navigation-split-view-primary-sidebar-min-width)` with flex-shrink: 0,
             so a width set on the pane itself only shrinks the pane INSIDE a
             wrapper that stays 320px — the icons narrow, the column does not,
             and the main content never moves left.
             The component's own stylesheet marks this variable as the way in
             ("read by JS via getComputedStyle in firstUpdated"), so overriding
             it here is the intended seam rather than reaching into the shadow
             DOM. */
          style={
            {
              '--_navigation-split-view-primary-sidebar-min-width': sidebarOpen || isMobile ? '240px' : '64px',
              transition: 'none',
            } as React.CSSProperties
          }
        >
          <nldd-split-view-pane slot="primary-sidebar" has-content background="tinted">
            <Sidebar mobile={isMobile} />
          </nldd-split-view-pane>

          <nldd-split-view-pane slot="main" has-content>
            <nldd-page>
              <div slot="header">
                <Header />
                <PlacementBanner />
              </div>
              <main id="main-content">
                <nldd-container padding="16" md-padding="24">
                  <Outlet />
                </nldd-container>
              </main>
            </nldd-page>
          </nldd-split-view-pane>

          {/* The inspector is the lowest-priority pane, so it is the first the
              split view hides when space runs short — which is what we want for
              the assistant. */}
          {chatOpen && (
            <nldd-split-view-pane slot="inspector" has-content background="base">
              <ChatPanel />
            </nldd-split-view-pane>
          )}
        </nldd-navigation-split-view>
      </nldd-shell>

      {/* Overlays live at the document root. Left as light-DOM siblings of the
          split view they get slotted into the main pane and steal its height. */}
      <ChatToggleButton />
      <SearchModal open={searchModalOpen} onClose={() => setSearchModalOpen(false)} />
      <GlobalDropOverlay visible={isDragging} />
      <FileActionChooser />
    </>
  );
}
