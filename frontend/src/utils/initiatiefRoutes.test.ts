import { describe, expect, it } from 'vitest';
import { initiatiefPath, isInitiatiefTab, isLeadDropPath } from './initiatiefRoutes';

describe('initiatiefPath', () => {
  it('leaves the default leads tab out of the path', () => {
    expect(initiatiefPath('abc')).toBe('/initiatieven/abc');
    expect(initiatiefPath('abc', 'leads')).toBe('/initiatieven/abc');
  });

  it('puts any other tab in the path', () => {
    expect(initiatiefPath('abc', 'signalen')).toBe('/initiatieven/abc/signalen');
  });
});

describe('isInitiatiefTab', () => {
  it('knows the tabs and nothing else', () => {
    expect(isInitiatiefTab('mensen')).toBe(true);
    expect(isInitiatiefTab('backlog')).toBe(true);
    expect(isInitiatiefTab('leden')).toBe(false);
    expect(isInitiatiefTab(undefined)).toBe(false);
  });
});

describe('isLeadDropPath', () => {
  it('accepts the overview and a leads tab', () => {
    expect(isLeadDropPath('/initiatieven')).toBe(true);
    expect(isLeadDropPath('/initiatieven/')).toBe(true);
    expect(isLeadDropPath('/initiatieven/abc')).toBe(true);
    expect(isLeadDropPath('/initiatieven/abc/leads')).toBe(true);
  });

  it('rejects the other tabs, where a new lead would surprise', () => {
    expect(isLeadDropPath('/initiatieven/abc/instellingen')).toBe(false);
    expect(isLeadDropPath('/initiatieven/abc/updates')).toBe(false);
  });

  it('rejects the rest of the app', () => {
    expect(isLeadDropPath('/corpus')).toBe(false);
    expect(isLeadDropPath('/initiatievenlijst')).toBe(false);
  });
});
