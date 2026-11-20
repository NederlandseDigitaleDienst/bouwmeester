import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';
import { useNlddEvent } from '@/components/nldd/events';

interface DocTab {
  id: string;
  label: string;
}

export function DocsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [tabs, setTabs] = useState<DocTab[]>([]);
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [tabsLoading, setTabsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tabBarRef = useRef<HTMLElement>(null);

  const tabParam = searchParams.get('tab');

  // Load the manifest once
  useEffect(() => {
    fetch('/docs/index.json')
      .then((res) => {
        if (!res.ok) throw new Error(`Kon documentatie-index niet laden (${res.status})`);
        return res.json();
      })
      .then((data: DocTab[]) => {
        setTabs(data);
        setTabsLoading(false);
      })
      .catch((err) => {
        setError(String(err));
        setTabsLoading(false);
      });
  }, []);

  // Determine active tab from URL or default to first
  const activeTab = tabs.find((t) => t.id === tabParam)?.id ?? tabs[0]?.id;

  // Load content when active tab changes
  useEffect(() => {
    if (!activeTab) return;
    setLoading(true);
    setError(null);
    fetch(`/docs/${activeTab}.md`)
      .then((res) => {
        if (!res.ok) throw new Error(`Kon documentatie niet laden (${res.status})`);
        return res.text();
      })
      .then((text) => {
        setContent(text);
        setLoading(false);
      })
      .catch((err) => {
        setError(String(err));
        setLoading(false);
      });
  }, [activeTab]);

  const handleTabChange = (tabId: string) => {
    setSearchParams({ tab: tabId });
  };

  // The bar reports the activated nldd-tab-bar-item element, not a value; the
  // tab id travels alongside on a data attribute so it can be read back here.
  useNlddEvent(tabBarRef, 'tab-change', (e) => {
    const detail = (e as CustomEvent<{ item?: HTMLElement }>).detail;
    const tabId = detail?.item?.dataset.tabId;
    if (tabId) handleTabChange(tabId);
  });

  if (tabsLoading) {
    return (
      <nldd-container max-width="800px">
        <LoadingSpinner padding="32" />
      </nldd-container>
    );
  }

  return (
    <nldd-container max-width="800px" gap="24">
      {tabs.length > 1 && (
        <nldd-tab-bar ref={tabBarRef} variant="text" accessible-label="Documentatie-onderdelen">
          {tabs.map((tab) => (
            <nldd-tab-bar-item
              key={tab.id}
              text={tab.label}
              current={tab.id === activeTab ? true : undefined}
              data-tab-id={tab.id}
            />
          ))}
        </nldd-tab-bar>
      )}

      {loading && (
        <LoadingSpinner padding="32" />
      )}
      {error && <nldd-banner variant="critical" size="sm" text={error} />}
      {!loading && !error && <MarkdownRenderer content={content} />}
    </nldd-container>
  );
}
