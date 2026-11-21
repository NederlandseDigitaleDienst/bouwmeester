import { useRef } from 'react';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { Icon } from '@/components/nldd/Icon';
import { useNlddEvent } from '@/components/nldd/events';
import { PersonAvatar } from '@/components/people/PersonAvatar';
import { formatFunctie } from '@/types';
import { richTextToPlain } from '@/utils/richtext';
import type { Person } from '@/types';

interface PersonCardProps {
  person: Person;
  onClick?: (person: Person) => void;
  draggable?: boolean;
  onDragStart?: (e: React.DragEvent, person: Person) => void;
}

interface ContactLinkProps {
  href: string;
  text: string;
  startIcon: string;
}

/**
 * `nldd-link` for a contact detail (email, phone) inside a card that is
 * itself clickable. The click bubbles same as a native anchor would, so it
 * is stopped here before it reaches the card's own open-detail handler.
 */
function ContactLink({ href, text, startIcon }: ContactLinkProps) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', (e) => e.stopPropagation());
  return (
    <nldd-link ref={ref} href={href} text={text} start-icon={startIcon} size="xs" />
  );
}

export function PersonCard({ person, onClick, draggable, onDragStart }: PersonCardProps) {
  const email = person.default_email || person.email;

  return (
    <Card
      // Only a button when there is something to activate. Without a handler
      // it is a card that happens to be draggable, and announcing it as a
      // button offers a control that does nothing.
      {...(onClick ? { actionLabel: person.naam } : { hoverable: false })}
      onClick={onClick ? () => onClick(person) : undefined}
      draggable={draggable}
      onDragStart={onDragStart ? (e: React.DragEvent) => onDragStart(e, person) : undefined}
    >
      {/*
        The identity carries the avatar and the name; the details sit under it
        rather than inside its `supporting-text` slot.

        That slot is a flex column sized by its content, with no `flex: 1`. An
        nldd-container slotted into it is a block with no intrinsic width, so
        the column has nothing to measure and collapses to zero: the name then
        wraps after every word and the card triples in height.

        The slots take rich text (a link, a <time>), not a layout of their own.
      */}
      <nldd-container gap="8">
        <nldd-identity text={person.naam}>
          {/* The avatar composes its own online dot, so it is slotted rather
              than left to nldd-identity's avatar-src (which only takes an
              image). */}
          <div slot="avatars">
            <PersonAvatar person={person} />
          </div>
          {person.is_agent && (
            <p slot="text">
              {person.naam} <Badge color="paars">Agent</Badge>
            </p>
          )}
        </nldd-identity>

        <nldd-container gap="4">
          {email && <ContactLink href={`mailto:${email}`} text={email} startIcon="envelope" />}
          {person.default_phone && (
            <ContactLink href={`tel:${person.default_phone}`} text={person.default_phone} startIcon="at" />
          )}
          {person.functie && (
            <nldd-container layout="row" gap="6" vertical-alignment="center">
              <Icon name="business-suitcase" size="xs" />
              <nldd-text size="xs" color="secondary"><p>{formatFunctie(person.functie)}</p></nldd-text>
            </nldd-container>
          )}
          {person.expertise && (
            <nldd-container layout="row" gap="6" vertical-alignment="center">
              <Icon name="tag" size="xs" />
              <nldd-text size="xs" color="secondary"><p>{person.expertise}</p></nldd-text>
            </nldd-container>
          )}
          {person.is_agent && person.description && (
            <nldd-text size="xs" color="secondary"><p>{richTextToPlain(person.description)}</p></nldd-text>
          )}
        </nldd-container>
      </nldd-container>
    </Card>
  );
}
