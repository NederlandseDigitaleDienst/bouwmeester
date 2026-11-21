import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';
import { MENTION_SCHEMES } from '@/utils/mentions';

/** `[label](scheme:id)` for any of our mention schemes. */
const MENTION_LINK_RE = new RegExp(
  `\\]\\((?:${Object.values(MENTION_SCHEMES).join('|')}):`,
);

// Regex to detect URLs in plain text.
// Matches http(s) URLs, then trims common trailing sentence punctuation that
// is unlikely to be part of the URL itself.
const URL_REGEX_RAW = /(https?:\/\/[^\s<>)"'\]]+)/;
const URL_REGEX_RAW_GLOBAL = new RegExp(URL_REGEX_RAW.source, 'g');
const TRAILING_PUNCT = /[.,;:!?]+$/;

/** Return true when href is a safe URL (http/https only). */
function isSafeHref(href: string): boolean {
  try {
    const url = new URL(href);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

interface RichTextDisplayProps {
  content: string | null | undefined;
  fallback?: string;
  /**
   * `inherit` lets text and links follow the surrounding color, for content on
   * a filled surface such as your own message bubble. Passed to nldd-rich-text.
   */
  color?: 'content' | 'inherit';
}

interface TipTapNode {
  type: string;
  content?: TipTapNode[];
  text?: string;
  attrs?: Record<string, unknown>;
  marks?: TipTapMark[];
}

interface TipTapMark {
  type: string;
  attrs?: Record<string, unknown>;
}

/** Does the text hold a mention token? Those are links, so they need the renderer. */
function containsMention(text: string): boolean {
  return MENTION_LINK_RE.test(text);
}

/** Simple heuristic: does the text contain markdown-like formatting? */
function looksLikeMarkdown(text: string): boolean {
  // Bold (**text** or __text__), italic (*text* or _text_), headers (#), lists (- or *)
  return /\*\*[^*]+\*\*|\*[^*]+\*|^#{1,3}\s|^[-*]\s/m.test(text);
}

/**
 * Extract plain text from a TipTap doc that only has paragraphs with unmarked
 * text nodes.  Returns null if the doc uses any rich features (marks, mentions).
 */
function extractPlainText(doc: TipTapNode): string | null {
  const lines: string[] = [];
  for (const node of doc.content ?? []) {
    if (node.type !== 'paragraph') return null;
    let line = '';
    for (const child of node.content ?? []) {
      if (child.type !== 'text' || (child.marks && child.marks.length > 0)) return null;
      line += child.text ?? '';
    }
    lines.push(line);
  }
  return lines.join('\n');
}

function isTipTapJson(value: string): TipTapNode | null {
  try {
    const parsed = JSON.parse(value);
    if (parsed && parsed.type === 'doc') return parsed;
  } catch {
    // Not JSON
  }
  return null;
}

export function RichTextDisplay({
  content,
  fallback = 'Geen beschrijving beschikbaar.',
  color = 'content',
}: RichTextDisplayProps) {
  const navigate = useNavigate();
  const { openTaskDetail } = useTaskDetail();
  const { openNodeDetail } = useNodeDetail();

  // Mention clicks are MarkdownRenderer's own business. Handling them here, in
  // a wrapper, would leave inert mention buttons in every caller that renders
  // MarkdownRenderer directly.
  const markdown = (value: string) => <MarkdownRenderer content={value} color={color} />;

  // nldd-text has no content channel on a filled surface, so `inherit` there.
  const plainColor = color === 'inherit' ? 'inherit' : 'secondary';

  if (!content) {
    return (
      <nldd-text size="sm" color={plainColor}>
        <p>{fallback}</p>
      </nldd-text>
    );
  }

  const doc = isTipTapJson(content);
  if (!doc) {
    // Detect markdown syntax and render accordingly
    // Markdown, or a mention token, which is markdown by construction. This is
    // what a stored description normally looks like.
    if (looksLikeMarkdown(content) || containsMention(content)) {
      // MarkdownRenderer brings its own nldd-rich-text.
      return markdown(content);
    }
    // Plain text fallback — auto-linkify URLs. `pre-wrap` is content, not
    // styling: the line breaks are the only structure this text has.
    //
    // It goes on a span inside the element, not on nldd-text itself. On the
    // host it is inherited into the shadow root, and the whitespace the
    // component's template has around its slot then renders too: every plain
    // description opened with an indent of a few words.
    return (
      <nldd-text size="sm" color={plainColor}>
        <span style={{ whiteSpace: 'pre-wrap' }}>{linkifyText(content)}</span>
      </nldd-text>
    );
  }

  // Legacy data: TipTap JSON with markdown syntax stored as plain text. The
  // editor converts markdown on input, so nothing writes this shape, but rows
  // in the database still hold it.
  const plainText = extractPlainText(doc);
  if (plainText !== null && looksLikeMarkdown(plainText)) {
    return markdown(plainText);
  }

  // nldd-rich-text styles the plain tags this renderer emits, which is why none
  // of the cases below carry classes any more.
  const handlers: MentionHandlers = { openTaskDetail, openNodeDetail, navigate };
  return (
    <nldd-rich-text spacing="tight" color={color}>
      {renderNodes(doc.content ?? [], handlers)}
    </nldd-rich-text>
  );
}

/**
 * An @person or #dossier chip inside running text.
 *
 * Clickable ones are a button wrapping the tag; the rest are just a tag. Never
 * make both a <button> and tell them apart by cursor alone: a screen reader
 * would offer a control that does nothing.
 */
function Mention({
  label,
  color,
  title,
  onClick,
}: {
  label: string;
  color: 'accent' | 'success' | 'neutral';
  title: string;
  onClick?: () => void;
}) {
  const tag = <nldd-tag text={label} color={color} size="sm" />;
  if (!onClick) return <span title={title}>{tag}</span>;
  // `plain-button`, not `all: unset`: that drops the focus ring along with the
  // chrome, and a control you cannot see focus on fails WCAG 2.4.7.
  return (
    <button type="button" className="plain-button" onClick={onClick} title={title}>
      {tag}
    </button>
  );
}

interface MentionHandlers {
  openTaskDetail: (id: string) => void;
  openNodeDetail: (id: string) => void;
  navigate: (path: string) => void;
}

function renderNodes(nodes: TipTapNode[], handlers: MentionHandlers): React.ReactNode[] {
  return nodes.map((node, i) => renderNode(node, i, handlers));
}

function renderNode(node: TipTapNode, key: number, handlers: MentionHandlers): React.ReactNode {
  switch (node.type) {
    case 'paragraph':
      return (
        <p key={key}>
          {node.content ? renderNodes(node.content, handlers) : null}
        </p>
      );

    case 'text':
      return renderText(node, key);

    case 'mention': {
      const id = node.attrs?.id as string | undefined;
      const label = node.attrs?.label as string | undefined;
      const mentionType = (node.attrs?.mentionType as string | undefined) ?? 'person';
      const isOrg = mentionType === 'organisatie';
      // A person mention goes nowhere, so it is not a button: a control that
      // does nothing when activated is worse than plain text to a screen
      // reader.
      return (
        <Mention
          key={key}
          label={`@${label}`}
          color={isOrg ? 'success' : 'accent'}
          title={isOrg ? `Afdeling: ${label}` : `Persoon: ${label}`}
          onClick={isOrg && id ? () => handlers.navigate(`/organisatie?eenheid=${id}`) : undefined}
        />
      );
    }

    case 'hashtagMention': {
      const id = node.attrs?.id as string | undefined;
      const label = node.attrs?.label as string | undefined;
      // Default to 'node' for legacy mentions that lack mentionType
      const mentionType = (node.attrs?.mentionType as string | undefined) ?? 'node';
      const isClickable = (mentionType === 'node' || mentionType === 'task') && !!id;
      return (
        <Mention
          key={key}
          label={`#${label}`}
          color="neutral"
          title={`${mentionType}: ${label}`}
          onClick={
            isClickable
              ? () => {
                  if (mentionType === 'node' && id) handlers.openNodeDetail(id);
                  else if (mentionType === 'task' && id) handlers.openTaskDetail(id);
                }
              : undefined
          }
        />
      );
    }

    case 'heading': {
      const level = (node.attrs?.level as number) ?? 2;
      const Tag = level === 2 ? 'h2' : 'h3';
      return (
        <Tag key={key}>
          {node.content ? renderNodes(node.content, handlers) : null}
        </Tag>
      );
    }

    case 'blockquote':
      return (
        <blockquote key={key}>
          {node.content ? renderNodes(node.content, handlers) : null}
        </blockquote>
      );

    case 'codeBlock':
      return (
        <pre key={key}>
          <code>{node.content?.map((c) => c.text ?? '').join('\n')}</code>
        </pre>
      );

    case 'horizontalRule':
      return <hr key={key} />;

    case 'hardBreak':
      return <br key={key} />;

    case 'bulletList':
      return (
        <ul key={key}>
          {node.content ? renderNodes(node.content, handlers) : null}
        </ul>
      );

    case 'orderedList':
      return (
        <ol key={key}>
          {node.content ? renderNodes(node.content, handlers) : null}
        </ol>
      );

    case 'listItem':
      return (
        <li key={key}>
          {node.content ? renderNodes(node.content, handlers) : null}
        </li>
      );

    default:
      // Fallback for unknown types: render content if available
      if (node.content) {
        return <span key={key}>{renderNodes(node.content, handlers)}</span>;
      }
      return null;
  }
}

function renderText(node: TipTapNode, key: number): React.ReactNode {
  const hasLinkMark = node.marks?.some((m) => m.type === 'link');

  // Auto-linkify plain text that has no explicit link mark
  let element: React.ReactNode = hasLinkMark
    ? (node.text ?? '')
    : linkifyText(node.text ?? '');

  if (node.marks) {
    for (const mark of node.marks) {
      switch (mark.type) {
        case 'bold':
          element = <strong key={key}>{element}</strong>;
          break;
        case 'italic':
          element = <em key={key}>{element}</em>;
          break;
        case 'code':
          element = <code key={key}>{element}</code>;
          break;
        case 'strike':
          element = <s key={key}>{element}</s>;
          break;
        case 'link': {
          const href = mark.attrs?.href as string | undefined;
          if (href && isSafeHref(href)) {
            element = (
              <a
                key={key}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
              >
                {element}
              </a>
            );
          }
          break;
        }
      }
    }
  }

  return <span key={key}>{element}</span>;
}

/**
 * Split text on URLs and return a mix of strings and <a> elements.
 * Trailing sentence punctuation (.,;:!?) is stripped from matched URLs
 * and appended as plain text so "Visit https://example.com." works correctly.
 */
function linkifyText(text: string): React.ReactNode {
  const parts = text.split(URL_REGEX_RAW_GLOBAL);
  if (parts.length === 1) return text; // no URLs found

  const result: React.ReactNode[] = [];
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    if (URL_REGEX_RAW.test(part)) {
      // Strip trailing punctuation that likely belongs to the sentence, not the URL
      const trimmed = part.replace(TRAILING_PUNCT, '');
      const trailing = part.slice(trimmed.length);
      result.push(
        <a
          key={`l${i}`}
          href={trimmed}
          target="_blank"
          rel="noopener noreferrer"
        >
          {trimmed}
        </a>,
      );
      if (trailing) {
        result.push(<React.Fragment key={`t${i}`}>{trailing}</React.Fragment>);
      }
    } else {
      result.push(<React.Fragment key={`p${i}`}>{part}</React.Fragment>);
    }
  }
  return result;
}
