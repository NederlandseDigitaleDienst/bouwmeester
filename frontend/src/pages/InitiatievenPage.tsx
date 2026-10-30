import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { useNlddEvent } from '@/components/nldd/events';
import { useInitiatieven } from '@/hooks/useInitiatieven';
import { useGlobalFileDropContext } from '@/hooks/useGlobalFileDropContext';
import { CreateInitiatiefModal } from '@/components/initiatieven/CreateInitiatiefModal';
import { initiatiefIconColor } from '@/components/initiatieven/initiatiefColors';
import { LeadIntakeDialog } from '@/components/leads/LeadIntakeDialog';
import { initiatiefPath } from '@/utils/initiatiefRoutes';
import { richTextToPlain } from '@/utils/richtext';
import { timeAgo } from '@/utils/dates';
import type { InitiatiefListItem } from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

/** True when the click asked for something other than plain navigation. */
function isModifiedClick(event: MouseEvent): boolean {
  return event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button === 1;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function figures(initiatief: InitiatiefListItem): string {
  const parts = [
    initiatief.lead_count === 0
      ? 'nog geen leads'
      : `${initiatief.active_lead_count} actief van ${plural(initiatief.lead_count, 'lead', 'leads')}`,
    plural(initiatief.member_count, 'lid', 'leden'),
  ];
  if (initiatief.last_published_at) parts.push(`update ${timeAgo(initiatief.last_published_at)}`);
  return parts.join(' · ');
}

/**
 * An initiatief on the overview. `nldd-card href` renders a real `<a>`, so
 * middle-click and cmd-click open a tab; a plain click goes through the
 * router instead of a full page load.
 *
 * The figures say whether an initiatief is alive without opening it: active
 * leads first (the parked ones in koelkast or in the pocket do not count),
 * then who is on it, then when it last told the outside world something.
 */
function InitiatiefCard({ initiatief }: { initiatief: InitiatiefListItem }) {
  const ref = useRef<HTMLElement>(null);
  const navigate = useNavigate();
  const to = initiatiefPath(initiatief.id);

  const onClick = useCallback(
    (event: Event) => {
      if (isModifiedClick(event as MouseEvent)) return;
      event.preventDefault();
      navigate(to);
    },
    [navigate, to],
  );
  useNlddEvent(ref, 'click', onClick);

  const description = richTextToPlain(initiatief.beschrijving);

  return (
    <nldd-card ref={ref} href={to} accessible-label={initiatief.naam}>
      <nldd-container gap="8" padding="16">
        <nldd-container layout="row" width="full" gap="8" vertical-alignment="center">
          <nldd-icon
            icon="circle-filled"
            size="16"
            color={initiatiefIconColor(initiatief.kleur)}
            aria-hidden="true"
          />
          <nldd-container width="fit-content" className="row-fill">
            <nldd-text size="sm" weight="bold">{initiatief.naam}</nldd-text>
          </nldd-container>
          {initiatief.public_page_enabled && (
            <nldd-tag text="Publiek" icon="globe" color="lintblauw" size="sm" />
          )}
        </nldd-container>

        {description && (
          <nldd-text size="xs" color="secondary" className="line-clamp-2">
            {description}
          </nldd-text>
        )}

        {/* One line of figures. As separate icon-and-text rows each took a
            full-width line, because a row container without a width fills
            its parent, and the card grew three lines taller than its text. */}
        <nldd-text size="xs" color="secondary">{figures(initiatief)}</nldd-text>
      </nldd-container>
    </nldd-card>
  );
}

/**
 * The initiatieven overview, and the menu's entry point. Each card opens the
 * initiatief's own page, whose first tab is its leads.
 */
export function InitiatievenPage() {
  const navigate = useNavigate();
  const { data: initiatieven = [], isLoading } = useInitiatieven();
  const [showCreate, setShowCreate] = useState(false);

  // A file dropped here still becomes a lead; the intake dialog asks which
  // initiatief it belongs to.
  const { subscribe } = useGlobalFileDropContext();
  const [droppedFiles, setDroppedFiles] = useState<File[]>([]);
  useEffect(() => subscribe((files) => setDroppedFiles(files)), [subscribe]);

  return (
    <nldd-container gap="24">
      <nldd-toolbar accessible-label="Initiatiefacties">
        <nldd-toolbar-item slot="start" priority={1} min-width="160px">
          <nldd-text size="sm" color="secondary">
            {isLoading ? '' : plural(initiatieven.length, 'initiatief', 'initiatieven')}
          </nldd-text>
        </nldd-toolbar-item>
        <nldd-toolbar-item slot="end">
          <NlddButton startIcon="plus" onClick={() => setShowCreate(true)} text="Nieuw initiatief" />
          <nldd-menu-item slot="overflow" text="Nieuw initiatief" icon="plus"></nldd-menu-item>
        </nldd-toolbar-item>
      </nldd-toolbar>

      {isLoading ? (
        <nldd-container layout="row" horizontal-alignment="center" padding="48">
          <LoadingSpinner />
        </nldd-container>
      ) : initiatieven.length === 0 ? (
        <nldd-container padding="48" horizontal-alignment="center">
          <nldd-text size="sm" color="secondary" horizontal-alignment="center">
            Je bent nog bij geen enkel initiatief betrokken.
          </nldd-text>
        </nldd-container>
      ) : (
        <nldd-collection layout="grid" item-min-width="296px" gap="12">
          {initiatieven.map((initiatief) => (
            <InitiatiefCard key={initiatief.id} initiatief={initiatief} />
          ))}
        </nldd-collection>
      )}

      {showCreate && (
        <CreateInitiatiefModal
          onClose={() => setShowCreate(false)}
          onCreated={(created) => {
            setShowCreate(false);
            navigate(initiatiefPath(created.id, 'instellingen'));
          }}
        />
      )}

      <LeadIntakeDialog
        open={droppedFiles.length > 0}
        onClose={() => setDroppedFiles([])}
        initialFiles={droppedFiles.length > 0 ? droppedFiles : undefined}
      />
    </nldd-container>
  );
}
