import { useCallback, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { SendMessageModal } from '@/components/common/SendMessageModal';
import { PersonAvatar } from '@/components/people/PersonAvatar';
import { Icon } from '@/components/nldd/Icon';
import { NlddButton } from '@/components/nldd/NlddButton';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { useNlddEvent } from '@/components/nldd/events';
import { usePersonSummary, usePersonOrganisaties, useUpdatePersonOrganisatie, useRemovePersonOrganisatie } from '@/hooks/usePeople';
import { useSamenwerkingsverbandenForPerson } from '@/hooks/useSamenwerkingsverbanden';
import { SAMENWERKINGSVERBAND_TYPE_LABELS, SAMENWERKINGSVERBAND_TYPE_BADGE_COLORS } from '@/types';
import { useCopyToClipboard } from '@/hooks/useCopyToClipboard';
import { formatFunctie, NODE_TYPE_COLORS, STAKEHOLDER_ROL_LABELS, DIENSTVERBAND_LABELS, PHONE_LABELS, TASK_PRIORITY_LABELS } from '@/types';
import { richTextToPlain } from '@/utils/richtext';
import { useVocabulary } from '@/contexts/VocabularyContext';
import { formatDateShort, todayISO } from '@/utils/dates';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import type { Person } from '@/types';

/** Priority -> the five semantic tag colors, for the task dot in the open-tasks list. */
const PRIORITY_DOT_COLORS: Record<string, 'critical' | 'warning' | 'accent' | 'neutral'> = {
  kritiek: 'critical',
  hoog: 'warning',
  normaal: 'accent',
  laag: 'neutral',
};

interface PersonCardExpandableProps {
  person: Person;
  onEditPerson?: (person: Person) => void;
  onDragStartPerson?: (e: React.DragEvent, person: Person) => void;
  isManager?: boolean;
  /** Override the manager badge label (e.g. "Coördinator" for teams) */
  managerLabel?: string;
  /** Extra badge shown on the right side (e.g. stakeholder role) */
  extraBadge?: React.ReactNode;
  /** Show end/delete buttons on placements (only on person/org pages) */
  showPlacementActions?: boolean;
}

/**
 * An external link (TK OData, Wikidata) inside a card that is itself
 * clickable. `nldd-link`'s click bubbles same as a native anchor would, so it
 * is stopped here before it reaches the card's own expand handler — same
 * pattern as `ContactLink` in PersonCard.tsx.
 */
function ExternalRefLink({ href, text }: { href: string; text: string }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', (e) => e.stopPropagation());
  return (
    <nldd-link ref={ref} href={href} text={text} target="_blank" size="xs" />
  );
}

/**
 * An internal route link (samenwerkingsverband detail) inside a card that
 * expands on click. `nldd-link` renders a real `<a>`; navigation goes through
 * the router instead of a full page load, and the click is stopped before it
 * reaches the card.
 */
function InternalRefLink({ to, text }: { to: string; text: string }) {
  const ref = useRef<HTMLElement>(null);
  const navigate = useNavigate();
  const onClick = useCallback(
    (event: Event) => {
      event.stopPropagation();
      const mouse = event as MouseEvent;
      if (mouse.metaKey || mouse.ctrlKey || mouse.shiftKey || mouse.altKey || mouse.button === 1) {
        return;
      }
      event.preventDefault();
      navigate(to);
    },
    [navigate, to],
  );
  useNlddEvent(ref, 'click', onClick);
  return <nldd-link ref={ref} href={to} text={text} size="xs" />;
}

export function PersonCardExpandable({ person, onEditPerson, onDragStartPerson, isManager, managerLabel, extraBadge, showPlacementActions }: PersonCardExpandableProps) {
  const [expanded, setExpanded] = useState(false);
  const { copied, copy } = useCopyToClipboard(1500);
  const [messageOpen, setMessageOpen] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const { nodeLabel } = useVocabulary();
  const { openTaskDetail } = useTaskDetail();
  const { openNodeDetail } = useNodeDetail();
  const { data: summary, isLoading: summaryLoading } = usePersonSummary(expanded ? person.id : null);
  const { data: placements } = usePersonOrganisaties(expanded ? person.id : null);
  const { data: lidmaatschappen } = useSamenwerkingsverbandenForPerson(
    expanded ? person.id : null,
  );
  const endPlacement = useUpdatePersonOrganisatie();
  const removePlacement = useRemovePersonOrganisatie();

  const displayEmail = person.default_email || person.email;
  const handleCopyEmail = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (displayEmail) {
      copy(displayEmail);
    }
  };

  return (
    <Card
      hoverable
      onClick={() => setExpanded(!expanded)}
      draggable={!!onDragStartPerson}
      onDragStart={onDragStartPerson ? (e: React.DragEvent) => onDragStartPerson(e, person) : undefined}
    >
      <nldd-container layout="row" gap="12">
        <PersonAvatar person={person} size="32" />
        <nldd-container width="fit-content" className="row-fill">
          <nldd-container layout="row" gap="8" vertical-alignment="center">
            {/* The name is the disclosure control: the card holds its own
                links and buttons, so it cannot be one itself, and without a
                control here the card would be mouse-only. It carries no
                chrome of its own, because a name is a name: the user-agent
                button styling would put a grey box around every person. */}
            <button
              type="button"
              className="plain-button"
              aria-expanded={expanded}
              onClick={(e) => {
                e.stopPropagation();
                setExpanded(!expanded);
              }}
              style={{ overflow: 'hidden', textAlign: 'left', minWidth: 0 }}
            >
              <nldd-text size="sm" weight="medium" className="truncate">
                {person.naam}
              </nldd-text>
            </button>
            {person.is_agent && <Badge color="paars">Agent</Badge>}
            {isManager && (() => {
              const label = managerLabel ?? 'Manager';
              return (
                <Badge color={label === 'Bewindspersoon' ? 'paars' : 'lintblauw'}>
                  {label}
                </Badge>
              );
            })()}
            {extraBadge && (
              <>
                <nldd-spacer direction="horizontal" size="flexible" />
                <div className="hug">{extraBadge}</div>
              </>
            )}
          </nldd-container>
          <nldd-container layout="wrap" gap="12" vertical-alignment="center">
            {displayEmail && (
              <button
                type="button"
                className="plain-button"
                onClick={handleCopyEmail}
                title="Klik om e-mail te kopiëren"
                style={{ display: 'flex', alignItems: 'center', gap: 'var(--primitives-space-4)', overflow: 'hidden' }}
              >
                <Icon name="envelope" size="xs" />
                <nldd-text size="xs" color="secondary" className="truncate">
                  {copied ? 'Gekopieerd!' : displayEmail}
                </nldd-text>
              </button>
            )}
            {person.default_phone && (
              <nldd-link
                href={`tel:${person.default_phone}`}
                size="xs"
                start-icon="at"
                text={person.default_phone}
                onClick={(e: React.MouseEvent) => e.stopPropagation()}
              />
            )}
            {person.functie && !person.is_agent && (
              // Hidden below sm by a wrapper, not on the hug itself: the
              // hidden-* utilities reset `display` above the breakpoint, and
              // on the same element that undid hug's inline-flex.
              <div className="hidden-below-sm-block" style={{ minWidth: 0 }}>
                <div className="hug hug-truncate" style={{ maxWidth: '100%' }}>
                  <Icon name="business-suitcase" size="xs" />
                  <nldd-text size="xs" color="secondary">
                    {formatFunctie(person.functie)}
                  </nldd-text>
                </div>
              </div>
            )}
            {person.description && person.is_agent && (
              <div className="hug hug-truncate hug-top">
                <Icon name="business-suitcase" size="xs" style={{ marginTop: '2px' }} />
                <nldd-text size="xs" color="secondary" className={expanded ? undefined : 'truncate'}>
                  {richTextToPlain(person.description)}
                </nldd-text>
              </div>
            )}
            {/* Externe links: TK OData, Wikidata */}
            {expanded && (person.tk_persoon_id || person.wikidata_qid) && (
              <div className="hug hug-gap-12">
                {person.tk_persoon_id && (
                  <ExternalRefLink
                    href={`https://www.tweedekamer.nl/kamerleden_en_commissies/alle_kamerleden/${person.tk_persoon_id}`}
                    text="Tweede Kamer ↗"
                  />
                )}
                {person.wikidata_qid && (
                  <ExternalRefLink
                    href={`https://www.wikidata.org/wiki/${person.wikidata_qid}`}
                    text={`Wikidata ${person.wikidata_qid} ↗`}
                  />
                )}
              </div>
            )}
          </nldd-container>
        </nldd-container>
        {/* Prominent message/prompt button — always visible. The card wraps
            everything in its own click-to-expand handler, and nldd-button's
            click bubbles same as a native button would, so this is stopped
            at capture before it reaches the card. */}
        <div style={{ flexShrink: 0 }} onClickCapture={(e) => e.stopPropagation()}>
          <NlddButton
            text={person.is_agent ? 'Prompt' : 'Bericht'}
            startIcon={person.is_agent ? 'terminal' : 'message-rectangle-text'}
            // Transparent, not tinted: this is one action per row, and a
            // filled button on every row competes with the names for
            // attention. It keeps its own hover and focus state.
            variant="neutral-transparent"
            size="sm"
            onClick={() => setMessageOpen(true)}
          />
        </div>
      </nldd-container>

      {/* Expanded details. nldd-divider draws the section separator (see the
          list-with-rows and page-with-sections patterns); the previous inline
          style invented a --semantics-border-color token that does not exist
          in the design system, so its hardcoded #e2e8f0 fallback was always
          the color actually applied. */}
      {expanded && (
        <>
          <nldd-spacer size="12" />
          <nldd-divider />
          <nldd-spacer size="12" />
          <nldd-container>
          {/* All emails */}
          {person.emails && person.emails.length > 0 && (
            <nldd-container padding-bottom="12">
              <nldd-container layout="row" gap="4" vertical-alignment="center">
                <Icon name="envelope" size="xs" />
                <nldd-text size="xs" color="secondary" weight="medium">E-mailadressen</nldd-text>
              </nldd-container>
              <nldd-container gap="2">
                {person.emails.map((em) => (
                  <nldd-container key={em.id} layout="row" gap="6" vertical-alignment="center">
                    {/* An unsized nldd-link runs inline, so the nldd-text
                        around it sets the size and can end it in an ellipsis. */}
                    <nldd-text size="xs" className="truncate">
                      <nldd-link
                        href={`mailto:${em.email}`}
                        text={em.email}
                        onClick={(e: React.MouseEvent) => e.stopPropagation()}
                      />
                    </nldd-text>
                    {em.is_default && <nldd-icon icon="star" size="16" color="warning" />}
                  </nldd-container>
                ))}
              </nldd-container>
            </nldd-container>
          )}
          {/* All phones */}
          {person.phones && person.phones.length > 0 && (
            <nldd-container padding-bottom="12">
              <nldd-container layout="row" gap="4" vertical-alignment="center">
                <Icon name="at" size="xs" />
                <nldd-text size="xs" color="secondary" weight="medium">Telefoonnummers</nldd-text>
              </nldd-container>
              <nldd-container gap="2">
                {person.phones.map((ph) => (
                  <nldd-container key={ph.id} layout="row" gap="6" vertical-alignment="center">
                    <nldd-link
                      href={`tel:${ph.phone_number}`}
                      size="xs"
                      text={ph.phone_number}
                      onClick={(e: React.MouseEvent) => e.stopPropagation()}
                    />
                    <nldd-text size="xs" color="secondary">
                      {PHONE_LABELS[ph.label] || ph.label}
                    </nldd-text>
                    {ph.is_default && <nldd-icon icon="star" size="16" color="warning" />}
                  </nldd-container>
                ))}
              </nldd-container>
            </nldd-container>
          )}
          {summaryLoading ? (
            <LoadingSpinner size="sm" padding="4" />
          ) : summary ? (
            <nldd-container gap="12">
              {/* Tasks section */}
              <nldd-container>
                <nldd-container layout="row" gap="12">
                  <div className="hug">
                    <Icon name="circle" size="xs" />
                    <nldd-text size="xs" color="secondary">{summary.open_task_count} open</nldd-text>
                  </div>
                  <div className="hug">
                    <Icon name="check-mark-circle" size="xs" />
                    <nldd-text size="xs" color="secondary">{summary.done_task_count} afgerond</nldd-text>
                  </div>
                </nldd-container>
                {summary.open_tasks.length > 0 && (
                  <nldd-list appearance="simple" dividers="never" accessible-label="Open taken">
                    {summary.open_tasks.map((task) => (
                      <nldd-list-item
                        key={task.id}
                        button
                        size="sm"
                        onClick={(e: React.MouseEvent) => {
                          e.stopPropagation();
                          openTaskDetail(task.id);
                        }}
                      >
                        <nldd-icon-cell size="16">
                          <nldd-tag
                            size="sm"
                            color={PRIORITY_DOT_COLORS[task.priority] ?? 'neutral'}
                            icon="circle-filled-extra-small"
                            variant="icon"
                            accessible-label={TASK_PRIORITY_LABELS[task.priority] ?? task.priority}
                          />
                        </nldd-icon-cell>
                        <nldd-text-cell size="sm" text={task.title} />
                        {task.due_date && (
                          <nldd-text-cell
                            size="sm"
                            color="secondary"
                            width="fit-content"
                            text={formatDateShort(task.due_date)}
                          />
                        )}
                      </nldd-list-item>
                    ))}
                  </nldd-list>
                )}
              </nldd-container>

              {/* Stakeholder nodes section */}
              {summary.stakeholder_nodes.length > 0 && (
                <nldd-list appearance="simple" dividers="never" accessible-label="Betrokken dossiers">
                  {summary.stakeholder_nodes.map((node) => (
                    <nldd-list-item
                      key={node.node_id}
                      button
                      size="sm"
                      onClick={(e: React.MouseEvent) => {
                        e.stopPropagation();
                        openNodeDetail(node.node_id);
                      }}
                    >
                      <nldd-icon-cell icon="file-text" size="16" color="secondary" />
                      <nldd-text-cell size="sm" text={node.node_title} />
                      <nldd-cell width="fit-content">
                        <Badge
                          color={NODE_TYPE_COLORS[node.node_type as keyof typeof NODE_TYPE_COLORS] || 'coolgray'}
                        >
                          {nodeLabel(node.node_type)}
                        </Badge>
                      </nldd-cell>
                      <nldd-text-cell
                        size="sm"
                        color="secondary"
                        width="fit-content"
                        text={STAKEHOLDER_ROL_LABELS[node.stakeholder_rol] || node.stakeholder_rol}
                      />
                    </nldd-list-item>
                  ))}
                </nldd-list>
              )}

              {/* Org placements section */}
              {placements && placements.length > 0 && (
                <nldd-container>
                  <nldd-container layout="row" gap="4" vertical-alignment="center">
                    <Icon name="apartment-building" size="xs" />
                    <nldd-text size="xs" color="secondary" weight="medium">Teams</nldd-text>
                  </nldd-container>
                  <nldd-container gap="4">
                    {placements.map((p) => (
                      <nldd-container key={p.id} layout="row" gap="8" vertical-alignment="center">
                        <nldd-text size="xs" className="truncate">
                          {p.organisatie_eenheid_naam}
                          {p.functietitel && (
                            <nldd-text size="xs" color="secondary"> — {p.functietitel}</nldd-text>
                          )}
                        </nldd-text>
                        <Badge color="coolgray">
                          {DIENSTVERBAND_LABELS[p.dienstverband] || p.dienstverband}
                        </Badge>
                        {showPlacementActions && (
                          <>
                          <nldd-spacer direction="horizontal" size="flexible" />
                          {/* A plain hug, not a row nldd-container: a size
                              container measures 0px wide beside a spacer. */}
                          <div className="hug">
                            {!p.eind_datum && (
                              <NlddIconButtonInline
                                icon="check-mark-circle"
                                accessibleLabel="Team-indeling beëindigen"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  endPlacement.mutate({
                                    personId: person.id,
                                    placementId: p.id,
                                    data: { eind_datum: todayISO() },
                                  });
                                }}
                              />
                            )}
                            {confirmDeleteId === p.id ? (
                              <div className="hug">
                                <nldd-text size="xs" color="critical">Zeker?</nldd-text>
                                <NlddTextButtonInline
                                  text="Ja"
                                  variant="critical-transparent"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    removePlacement.mutate(
                                      { personId: person.id, placementId: p.id },
                                      { onSettled: () => setConfirmDeleteId(null) },
                                    );
                                  }}
                                />
                                <NlddTextButtonInline
                                  text="Nee"
                                  variant="neutral-transparent"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setConfirmDeleteId(null);
                                  }}
                                />
                              </div>
                            ) : (
                              <NlddIconButtonInline
                                icon="close"
                                accessibleLabel="Team-indeling verwijderen"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setConfirmDeleteId(p.id);
                                }}
                              />
                            )}
                          </div>
                          </>
                        )}
                      </nldd-container>
                    ))}
                  </nldd-container>
                </nldd-container>
              )}

              {/* Samenwerkingsverbanden */}
              {lidmaatschappen && lidmaatschappen.length > 0 && (
                <nldd-container>
                  <nldd-container layout="row" gap="4" vertical-alignment="center">
                    <Icon name="handshake" size="xs" />
                    <nldd-text size="xs" color="secondary" weight="medium">Samenwerkingsverbanden</nldd-text>
                  </nldd-container>
                  <nldd-container gap="4">
                    {lidmaatschappen.map((lid) => (
                      <nldd-container key={lid.id} layout="row" gap="8" vertical-alignment="center">
                        <InternalRefLink
                          to={`/samenwerkingsverbanden/${lid.samenwerkingsverband_id}`}
                          text={lid.samenwerkingsverband_naam}
                        />
                        <Badge
                          color={
                            SAMENWERKINGSVERBAND_TYPE_BADGE_COLORS[
                              lid.samenwerkingsverband_type
                            ] ?? 'coolgray'
                          }
                        >
                          {SAMENWERKINGSVERBAND_TYPE_LABELS[
                            lid.samenwerkingsverband_type
                          ] ?? lid.samenwerkingsverband_type}
                        </Badge>
                        {lid.rol && (
                          <nldd-text size="xs" color="secondary">— {lid.rol}</nldd-text>
                        )}
                      </nldd-container>
                    ))}
                  </nldd-container>
                </nldd-container>
              )}

              {/* No tasks and no nodes */}
              {summary.open_task_count === 0 && summary.done_task_count === 0 && summary.stakeholder_nodes.length === 0 && (!placements || placements.length === 0) && (!lidmaatschappen || lidmaatschappen.length === 0) && (
                <nldd-text size="xs" color="secondary">Geen taken, dossiers of teams.</nldd-text>
              )}
            </nldd-container>
          ) : null}

          {/* Edit button. Same divider fix as above: nldd-divider instead of
              an invented border-color token. */}
          {onEditPerson && (
            <>
              <nldd-spacer size="8" />
              <nldd-divider />
              <nldd-container
                layout="row"
                horizontal-alignment="right"
                padding-top="8"
                onClickCapture={(e: React.MouseEvent) => e.stopPropagation()}
              >
                <NlddButton
                  text="Bewerken"
                  startIcon="pencil"
                  variant="neutral-transparent"
                  size="sm"
                  onClick={() => onEditPerson(person)}
                />
              </nldd-container>
            </>
          )}
          </nldd-container>
        </>
      )}

      <SendMessageModal
        open={messageOpen}
        onClose={() => setMessageOpen(false)}
        recipient={person}
      />
    </Card>
  );
}

/** Small icon-only action button local to placement rows: neutral, xs, stops
 *  its own click before it reaches the card's expand handler. */
function NlddIconButtonInline({
  icon,
  accessibleLabel,
  onClick,
}: {
  icon: string;
  accessibleLabel: string;
  onClick: (e: React.MouseEvent) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', (e) => onClick(e as unknown as React.MouseEvent));
  return (
    <nldd-icon-button
      ref={ref}
      icon={icon}
      appearance="neutral-transparent"
      size="xs"
      accessible-label={accessibleLabel}
    />
  );
}

/** The text-labelled twin of NlddIconButtonInline, for the Ja/Nee confirm on a
 *  placement row: same xs sizing and same click-stopping, transparent so a row
 *  of actions does not become a row of filled blocks. */
function NlddTextButtonInline({
  text,
  variant,
  onClick,
}: {
  text: string;
  variant: 'critical-transparent' | 'neutral-transparent';
  onClick: (e: React.MouseEvent) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', (e) => onClick(e as unknown as React.MouseEvent));
  return <nldd-button ref={ref} text={text} appearance={variant} size="xs" />;
}
