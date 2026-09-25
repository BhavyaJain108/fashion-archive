import React from 'react';
import { act, fireEvent, render } from '@testing-library/react';
import JustifiedGrid from './JustifiedGrid';
import { DESKTOP } from './justified';

// jsdom has no layout: give the container a width and images real dimensions.
beforeAll(() => {
  Element.prototype.getBoundingClientRect = function () {
    return { width: 1000, height: 0, top: 0, left: 0, right: 1000, bottom: 0 };
  };
});

const items = [
  { key: 'a', w: 600, h: 800 },   // portrait 0.75
  { key: 'b', w: 1200, h: 800 },  // landscape 1.5
  { key: 'c', w: 800, h: 800 },   // square 1
  { key: 'd', w: 600, h: 900 },   // 0.667
  { key: 'e', w: 600, h: 800 },
  { key: 'f', w: 1600, h: 800 },  // 2
  { key: 'g', w: 600, h: 800 },
];

function Tile({ item, box }) {
  return (
    <div className="tile" data-key={item.key} style={{ width: box.width, height: box.height }}>
      <img alt="" data-key={item.key} onLoad={(e) => box.onRatio(e.currentTarget.naturalWidth / e.currentTarget.naturalHeight)} />
    </div>
  );
}

test('rows re-flow to the loaded aspect ratios and fill the width exactly, nothing cropped', () => {
  const { container } = render(
    <JustifiedGrid items={items} keyOf={(i) => i.key} renderTile={(i, box) => <Tile item={i} box={box} />} />
  );
  act(() => {
    for (const it of items) {
      const img = container.querySelector(`img[data-key="${it.key}"]`);
      Object.defineProperty(img, 'naturalWidth', { value: it.w, configurable: true });
      Object.defineProperty(img, 'naturalHeight', { value: it.h, configurable: true });
      fireEvent.load(img);
    }
  });
  const rows = [...container.querySelectorAll('.jg-row')];
  expect(rows.length).toBeGreaterThan(1);
  for (const row of rows) {
    const tiles = [...row.querySelectorAll('.tile')];
    const widths = tiles.map((t) => parseFloat(t.style.width));
    const height = parseFloat(tiles[0].style.height);
    const sum = widths.reduce((s, w) => s + w, 0) + DESKTOP.gap * (tiles.length - 1);
    if (!row.classList.contains('ragged')) {
      expect(Math.abs(sum - 1000)).toBeLessThan(0.5);
      expect(height).toBeGreaterThanOrEqual(DESKTOP.min);
      expect(height).toBeLessThanOrEqual(DESKTOP.max);
    }
    // every tile's box is exactly its photograph's proportions: no crop possible
    for (const t of tiles) {
      const it = items.find((i) => i.key === t.dataset.key);
      expect(parseFloat(t.style.width) / parseFloat(t.style.height)).toBeCloseTo(it.w / it.h, 3);
    }
  }
});
