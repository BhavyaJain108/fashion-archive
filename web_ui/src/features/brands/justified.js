// Justified rows: every row one height, every image its own aspect ratio,
// scaled so the widths add up to the row width exactly. Nothing is cropped.
//
// Given aspect ratios r_i (width / height), a row of items i..j at width W with
// gap g has one height that fills it: h = (W - g·(n-1)) / Σ r_i. Choosing where
// rows break is the whole problem: a dynamic program over break points that
// minimises Σ (h - target)² subject to min ≤ h ≤ max. The last row is the one
// exception — if what is left cannot fill the width inside the band it is laid
// out at the target height and left aligned, and `rows[last].ragged` says so.

export const DESKTOP = { target: 320, min: 240, max: 440, gap: 16 };
export const PHONE = { target: 200, min: 150, max: 280, gap: 12 };

export function limitsFor(width) {
  return width < 700 ? PHONE : DESKTOP;
}

function rowHeight(ratios, from, to, width, gap) {
  let sum = 0;
  for (let i = from; i < to; i++) sum += ratios[i];
  return (width - gap * (to - from - 1)) / sum;
}

/**
 * @param {number[]} ratios  width/height per item, in order
 * @param {number} width     container width in px
 * @param {{target:number,min:number,max:number,gap:number}} limits
 * @returns {{height:number, items:{index:number,width:number}[], ragged:boolean}[]}
 */
export function layoutRows(ratios, width, limits = DESKTOP) {
  const n = ratios.length;
  if (!n || width <= 0) return [];
  const { target, min, max, gap } = limits;
  const INF = Number.POSITIVE_INFINITY;
  // best[j] = least cost to lay out items 0..j-1 in complete rows; prev[j] = start of the last row
  const best = new Array(n + 1).fill(INF);
  const prev = new Array(n + 1).fill(-1);
  best[0] = 0;
  for (let j = 1; j <= n; j++) {
    for (let i = j - 1; i >= 0; i--) {
      if (best[i] === INF) continue;
      const h = rowHeight(ratios, i, j, width, gap);
      if (h > max) continue; // too few items: taller than allowed. Adding more only lowers h.
      if (h < min) break; // too many items: shorter than allowed, and fewer starts (i smaller) only shorten it
      const cost = best[i] + (h - target) * (h - target);
      if (cost < best[j]) { best[j] = cost; prev[j] = i; }
    }
  }
  // Find the longest prefix that lays out inside the band; what is left is the ragged tail.
  let end = n;
  while (end > 0 && best[end] === INF) end--;
  const rows = [];
  let j = end;
  while (j > 0) {
    const i = prev[j];
    const h = rowHeight(ratios, i, j, width, gap);
    rows.unshift({ height: h, ragged: false, items: range(i, j).map((k) => ({ index: k, width: ratios[k] * h })) });
    j = i;
  }
  if (end < n) {
    // The tail: at the target height unless that alone would overflow the width.
    const natural = rowHeight(ratios, end, n, width, gap);
    const h = Math.min(target, natural);
    rows.push({ height: h, ragged: natural > target, items: range(end, n).map((k) => ({ index: k, width: ratios[k] * h })) });
  }
  return rows;
}

const range = (a, b) => Array.from({ length: b - a }, (_, k) => a + k);
