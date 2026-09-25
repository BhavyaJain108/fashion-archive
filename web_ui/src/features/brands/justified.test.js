import { layoutRows, DESKTOP } from './justified';

const width = 1000;
const sum = (row) => row.items.reduce((s, it) => s + it.width, 0) + DESKTOP.gap * (row.items.length - 1);

test('every full row fills the width exactly and stays inside the band', () => {
  const ratios = [0.75, 0.75, 1.5, 0.66, 1, 0.75, 0.8, 1.33, 0.75, 0.75, 0.7, 0.75];
  const rows = layoutRows(ratios, width);
  expect(rows.length).toBeGreaterThan(1);
  for (const row of rows.filter((r) => !r.ragged)) {
    expect(Math.abs(sum(row) - width)).toBeLessThan(0.5);
    expect(row.height).toBeGreaterThanOrEqual(DESKTOP.min);
    expect(row.height).toBeLessThanOrEqual(DESKTOP.max);
  }
  // every item placed once, in order
  expect(rows.flatMap((r) => r.items.map((i) => i.index))).toEqual(ratios.map((_, i) => i));
});

test('a tail that cannot fill the width is ragged at the target height, never stretched', () => {
  const rows = layoutRows([0.75, 0.75, 0.75, 0.75, 0.75], width);
  const last = rows[rows.length - 1];
  // five portraits: one row of them is 1000/3.75 = 253px tall — inside the band, so no rag
  expect(last.ragged).toBe(false);
  const one = layoutRows([0.75], width);
  expect(one[0].ragged).toBe(true);
  expect(one[0].height).toBe(DESKTOP.target);
  expect(one[0].items[0].width).toBeCloseTo(0.75 * DESKTOP.target);
});

test('rows prefer the target height over the extremes of the band', () => {
  const ratios = new Array(20).fill(0.75);
  const rows = layoutRows(ratios, width);
  for (const row of rows.filter((r) => !r.ragged)) expect(Math.abs(row.height - DESKTOP.target)).toBeLessThan(60);
});

test('no items, no rows', () => {
  expect(layoutRows([], width)).toEqual([]);
});
