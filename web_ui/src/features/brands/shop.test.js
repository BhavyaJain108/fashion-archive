import { columnsFor, groupRows, pageRows, rowTops, shapeKey, windowRange } from './shop';

const t = (id, ratio) => ({ url: id, ratio });

test('columns follow the stylesheet breakpoints', () => {
  expect(columnsFor(1800)).toBe(4);
  expect(columnsFor(1200)).toBe(3);
  expect(columnsFor(700)).toBe(3);
  expect(columnsFor(400)).toBe(2);
});

test('a row takes its first picture\'s shape and pulls nearby matches', () => {
  const tiles = [t('a', 0.75), t('b', 1.0), t('c', 0.75), t('d', 0.75), t('e', 1.0), t('f', 1.0)];
  expect(groupRows(tiles, 3).map((x) => x.url)).toEqual(['a', 'c', 'd', 'b', 'e', 'f']);
});

test('nothing moves further than the lookahead, and leftovers keep their order', () => {
  const tiles = [t('a', 0.75), ...Array.from({ length: 9 }, (_, i) => t(`s${i}`, 1.0)), t('z', 0.75)];
  const out = groupRows(tiles, 3).map((x) => x.url);
  expect(out[0]).toBe('a');
  expect(out.slice(1, 3)).toEqual(['s0', 's1']); // z is ten away: out of reach, so the row is mixed
  expect(out.indexOf('z')).toBe(10);
});

test('unknown shapes never pull anything and 0.74 lands with 0.76', () => {
  expect(shapeKey(t('x', null))).toBeNull();
  expect(shapeKey(t('x', 0.74))).toBe(shapeKey(t('y', 0.76)));
  const tiles = [t('a', null), t('b', 0.75), t('c', 0.75)];
  expect(groupRows(tiles, 2).map((x) => x.url)).toEqual(['a', 'b', 'c']);
});

test('pages are grouped on their own, so a drawn page never changes when the next arrives', () => {
  const page1 = [t('a', 0.75), t('b', 1.0), t('c', 0.75)];
  const page2 = [t('d', 1.0), t('e', 0.75), t('f', 1.0)];
  const before = pageRows(page1, 3, 3);
  const after = pageRows([...page1, ...page2], 3, 3);
  expect(after[0]).toEqual(before[0]);
  expect(after.length).toBe(2);
});

test('row tops use measured heights where known and the estimate elsewhere', () => {
  expect(rowTops({ 1: 250 }, 400, 3)).toEqual([0, 400, 650, 1050]);
});

test('the window covers the viewport plus overscan and never leaves the rows', () => {
  const tops = rowTops({}, 100, 10); // ten rows of 100px
  expect(windowRange(0, 250, tops, 10, 1)).toEqual([0, 4]);   // rows 0-2 visible, one more below
  expect(windowRange(450, 250, tops, 10, 1)).toEqual([3, 8]); // rows 4-6 visible, one each side
  expect(windowRange(950, 250, tops, 10, 1)).toEqual([8, 10]);
  expect(windowRange(0, 250, [], 0, 1)).toEqual([0, 0]);
});
