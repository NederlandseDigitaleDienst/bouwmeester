import { describe, expect, it } from 'vitest';
import {
  ALL_PARLEMENTAIR_TYPES,
  PARLEMENTAIR_TYPE_COLORS,
  PARLEMENTAIR_TYPE_LABELS,
} from './index';

describe('parlementair types', () => {
  it.each(['tkconv_document', 'nieuwsartikel', 'bekendmaking'])(
    'knows backend type %s, so the type filter can tick it back on',
    (type) => {
      expect(ALL_PARLEMENTAIR_TYPES).toContain(type);
      expect(PARLEMENTAIR_TYPE_LABELS[type]).toBeTruthy();
      expect(PARLEMENTAIR_TYPE_COLORS[type]).toBeTruthy();
    },
  );

  it('gives every type a label and a color', () => {
    for (const type of ALL_PARLEMENTAIR_TYPES) {
      expect(PARLEMENTAIR_TYPE_LABELS[type]).toBeTruthy();
      expect(PARLEMENTAIR_TYPE_COLORS[type]).toBeTruthy();
    }
  });
});
