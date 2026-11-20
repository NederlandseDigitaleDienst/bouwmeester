import { isPersonOnline } from '@/utils/people';

/** nldd-avatar only accepts spacer-aligned pixel sizes. */
type AvatarSize = '24' | '28' | '32' | '40' | '44' | '48';

interface PersonAvatarProps {
  person: { naam: string; is_agent: boolean; last_seen_at?: string | null };
  /** A size from the spacer-aligned set nldd-avatar accepts. Defaults to '40'. */
  size?: AvatarSize;
}

/**
 * A person's avatar, with an online dot.
 *
 * The element derives initials from `name` itself and falls back to an icon
 * when there is nothing to derive (an empty name) or when `icon` is set
 * explicitly, which is what marks an agent here: 'sparkles' rather than a
 * literal robot glyph, matching the icon bridge's own choice for `Bot`. The
 * online dot is `nldd-badge`, the design system's small count/status overlay:
 * icon-only with no text or number it renders as a plain dot, and `pulse`
 * gives it a live read.
 */
export function PersonAvatar({ person, size = '40' }: PersonAvatarProps) {
  const online = isPersonOnline(person);

  return (
    // The badge anchors to this box with absolute positioning, which is layout
    // math a component can't express — nldd-container has no relative/absolute
    // concept, so this one div stays plain CSS (inline style, no className).
    <div style={{ position: 'relative', flexShrink: 0, width: `${size}px`, height: `${size}px` }}>
      <nldd-avatar
        name={person.naam}
        size={size}
        {...(person.is_agent ? { icon: 'sparkles', color: 'content' } : {})}
      />
      {online && (
        // Same reason: the online dot is pinned to a corner of the avatar box,
        // not laid out relative to a sibling.
        <nldd-badge
          color="success"
          icon="circle-filled-extra-small"
          pulse
          decorative
          style={{ position: 'absolute', bottom: 0, right: 0 }}
        />
      )}
    </div>
  );
}
