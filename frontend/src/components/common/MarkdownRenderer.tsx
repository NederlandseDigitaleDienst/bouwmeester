import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import DOMPurify from 'dompurify';
import { useNavigate } from 'react-router-dom';
import { parseMention, mentionSigil, MENTION_SCHEMES } from '@/utils/mentions';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'neutral',
  securityLevel: 'strict',
  fontFamily: 'inherit',
});

let mermaidCounter = 0;

function MermaidBlock({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const id = `mermaid-${++mermaidCounter}`;
    mermaid
      .render(id, chart)
      .then(({ svg: rendered }) => {
        if (!cancelled) setSvg(DOMPurify.sanitize(rendered, { USE_PROFILES: { svg: true, svgFilters: true } }));
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [chart]);

  if (error) {
    return <nldd-banner variant="critical" text="Diagram kon niet worden getekend" supporting-text={error} />;
  }

  // `data-rich-text-width="wide"` puts the diagram in the media zone, the same one
  // rich-text gives images and tables, so a wide diagram gets the extra room
  // instead of being squeezed into the reading column.
  return <div ref={ref} data-rich-text-width="wide" dangerouslySetInnerHTML={{ __html: svg }} />;
}

/** Parse bm:// links and return { type, id } or null for regular links. */
function parseBmLink(href: string | undefined): { type: 'node' | 'task' | 'lead'; id: string } | null {
  if (!href) return null;
  const match = href.match(/^bm:\/\/(node|task|lead)\/([a-f0-9-]+)$/i);
  if (!match) return null;
  return { type: match[1] as 'node' | 'task' | 'lead', id: match[2] };
}

/**
 * Only the elements that carry behaviour are overridden.
 *
 * Headings, paragraphs, lists, blockquotes, tables, rules and inline code used
 * to be twenty hand-styled overrides here. `nldd-rich-text` styles plain HTML
 * directly (it renders without a shadow root for exactly this reason), so they
 * are gone and the markdown now produces ordinary tags. That also means the
 * responsive type scale and the heading rhythm come from the system rather
 * than from a set of numbers that happened to be typed in this file.
 */
const components: Components = {
  a: ({ href, children }) => {
    // A mention: a link carrying a scheme, written by the editor and by the
    // backend. Rendered as a chip that opens the thing it names.
    const mention = href ? parseMention(href, String(children ?? '')) : null;
    if (mention) {
      return (
        <button
          type="button"
          className="plain-button"
          data-mention-kind={mention.kind}
          data-mention-id={mention.id}
        >
          <nldd-tag
            text={`${mentionSigil(mention.kind)}${mention.label}`}
            color={mention.kind === 'person' || mention.kind === 'organisatie' ? 'accent' : 'neutral'}
            size="sm"
          />
        </button>
      );
    }

    const bm = parseBmLink(href);
    if (bm) {
      // A button, not a link: it navigates inside the app and has no URL to
      // open in a new tab. Click handling sits on the container, so this only
      // has to carry the target. `plain-button` drops the browser chrome; the
      // color and underline repeat what nldd-rich-text gives a raw <a>, so it
      // still reads as a link in running text.
      return (
        <button
          type="button"
          className="plain-button"
          style={{ color: 'var(--semantics-links-color)', textDecoration: 'underline' }}
          data-bm-type={bm.type}
          data-bm-id={bm.id}
        >
          {children}
        </button>
      );
    }
    // A raw <a> inside nldd-rich-text, not nldd-link: link components are for
    // UI navigation, running text uses the real element.
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
  code: ({ className, children, ...props }) => {
    const match = /language-(\w+)/.exec(className || '');
    if (match?.[1] === 'mermaid') {
      return <MermaidBlock chart={String(children).trim()} />;
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
  pre: ({ children }) => {
    // A mermaid diagram replaces the code block entirely, so it must not end up
    // wrapped in a <pre>.
    const child = children as ReactNode;
    if (
      child &&
      typeof child === 'object' &&
      'type' in (child as unknown as Record<string, unknown>) &&
      (child as unknown as { type: unknown }).type === MermaidBlock
    ) {
      return <>{children}</>;
    }
    // A plain <pre>, not nldd-code-viewer: that element is CodeMirror, which
    // register.ts keeps out of the main chunk, and nldd-rich-text styles <pre>.
    return <pre>{children}</pre>;
  },
};

/**
 * Compact additionally demotes the headings by two levels.
 *
 * This is the one piece of the old component map that could not go. Compact
 * renders inside a chat bubble, and an assistant reply regularly opens with an
 * `#` heading; at the document scale that heading is larger than the whole
 * conversation around it. rich-text has a spacing scale but no size scale, so
 * the demotion stays here. It is a real property of the surface, not styling:
 * a heading inside a message is subordinate to the page it sits on.
 *
 * Demoting the tag rather than restyling it also keeps the document outline
 * honest, which an h1-styled-as-h5 would not.
 */
const compactComponents: Components = {
  ...components,
  h1: ({ children }) => <h3>{children}</h3>,
  h2: ({ children }) => <h4>{children}</h4>,
  h3: ({ children }) => <h5>{children}</h5>,
  h4: ({ children }) => <h6>{children}</h6>,
};

interface MarkdownRendererProps {
  content: string;
  compact?: boolean;
  onBmLink?: (type: 'node' | 'task' | 'lead', id: string) => void;
  /** Passed to nldd-rich-text: `inherit` follows the color of a filled surface. */
  color?: 'content' | 'inherit';
}

export function MarkdownRenderer({ content, compact, onBmLink, color = 'content' }: MarkdownRendererProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const navigate = useNavigate();
  const { openTaskDetail } = useTaskDetail();
  const { openNodeDetail } = useNodeDetail();

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      // Mentions are handled here rather than by each caller. The chip above
      // is a real button with a real tab stop, so any caller that renders
      // MarkdownRenderer directly (chat, the parlementair summary, the docs
      // page) would otherwise offer a button that does nothing.
      const mention = (e.target as HTMLElement).closest<HTMLElement>('[data-mention-kind]');
      if (mention) {
        const kind = mention.dataset.mentionKind;
        const id = mention.dataset.mentionId;
        if (kind && id) {
          e.preventDefault();
          if (kind === 'node') openNodeDetail(id);
          else if (kind === 'task') openTaskDetail(id);
          else if (kind === 'organisatie') navigate(`/organisatie?eenheid=${id}`);
          // A person mention goes nowhere: there is no person detail surface.
          return;
        }
      }

      if (!onBmLink) return;
      const target = (e.target as HTMLElement).closest<HTMLButtonElement>('[data-bm-type]');
      if (!target) return;
      const type = target.dataset.bmType as 'node' | 'task' | 'lead';
      const id = target.dataset.bmId;
      if (type && id) {
        e.preventDefault();
        onBmLink(type, id);
      }
    },
    [onBmLink, navigate, openNodeDetail, openTaskDetail],
  );

  // `compact` was a second copy of the whole component map with smaller
  // margins everywhere. The margins are now the spacing scale, so only the
  // heading demotion is left of it.
  return (
    <div ref={containerRef} onClick={handleClick}>
      <nldd-rich-text spacing={compact ? 'tight' : 'snug'} color={color}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={compact ? compactComponents : components}
          urlTransform={(url) => {
            // Allow bm:// protocol links for in-app navigation
            if (url.startsWith('bm://')) return url;
            // ...and the mention schemes, which are links by construction.
            if (Object.values(MENTION_SCHEMES).some((s) => url.startsWith(`${s}:`))) return url;
            // Default: only allow http, https, mailto
            if (/^https?:\/\/|^mailto:/i.test(url)) return url;
            return '';
          }}
        >
          {content}
        </ReactMarkdown>
      </nldd-rich-text>
    </div>
  );
}
