import { describe, expect, it } from 'vitest';

import { heeftVerwijzing } from './publiekeTekst';

describe('heeftVerwijzing', () => {
  it('ziet de verwijzingen uit de editor', () => {
    expect(heeftVerwijzing('Dank aan [@Anne](user:3fa9)')).toBe(true);
    expect(heeftVerwijzing('Zie [#Belronde](task:12)')).toBe(true);
    expect(heeftVerwijzing('Bij [@BZK](ORG:1)')).toBe(true);
    expect(heeftVerwijzing('Volgens [#Wet](node:1)')).toBe(true);
  });

  it('ook met een spatie of punthaken voor het doel', () => {
    expect(heeftVerwijzing('[@Anne]( user:3fa9)')).toBe(true);
    expect(heeftVerwijzing('[@Anne](<user:3fa9>)')).toBe(true);
  });

  it('laat gewone tekst en gewone links door', () => {
    expect(heeftVerwijzing('Gewoon @Anne, zonder link')).toBe(false);
    expect(heeftVerwijzing('[de wet](https://wetten.overheid.nl)')).toBe(false);
    expect(heeftVerwijzing(null, undefined, '')).toBe(false);
  });

  it('kijkt naar alle teksten', () => {
    expect(heeftVerwijzing('schoon', '[@A](user:1)')).toBe(true);
  });
});
