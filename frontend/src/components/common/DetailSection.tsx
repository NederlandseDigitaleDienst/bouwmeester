import type { ReactNode } from 'react';

interface DetailSectionProps {
  title: string;
  icon?: ReactNode;
  count?: number;
  action?: ReactNode;
  separated?: boolean;
  children: ReactNode;
}

/**
 * A titled block inside a detail view.
 *
 * The heading is a small, bold, secondary `nldd-text` rather than an
 * `nldd-title`: these sit inside a modal that already has its own heading, and
 * a second heading level here would make the document outline claim more
 * structure than there is.
 */
export function DetailSection({
  title,
  icon,
  count,
  action,
  separated = false,
  children,
}: DetailSectionProps) {
  return (
    <nldd-container gap="8">
      {separated && <nldd-divider />}
      <nldd-container layout="row" gap="8" vertical-alignment="center">
        <nldd-container layout="row" gap="6" vertical-alignment="center">
          {icon}
          <nldd-text size="xs" weight="bold" color="secondary">
            <p>
              {count != null ? `${title} (${count})` : title}
            </p>
          </nldd-text>
        </nldd-container>
        {action && (
          <div className="hug hug-stack hug-end">
            {action}
          </div>
        )}
      </nldd-container>
      {children}
    </nldd-container>
  );
}
