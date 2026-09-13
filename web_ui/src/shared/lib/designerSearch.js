// Ranking 8,657 designer names against what someone has typed.
//
// Fuse.js was the obvious choice — it is already a dependency — but it ranks
// this badly. Its score has no notion of where in a name a match landed, so
// "yoji" returned Esau Yori, Jojie Lioren and Koji Nihomatsu while Yohji
// Yamamoto did not appear at all, and "margela" put Marmelade above Martin
// Margiela. For a list of proper nouns, where a match on the first word of a
// name is worth far more than a match in the middle of another, that ordering
// is the whole feature.
//
// So this ranks in tiers, cheapest and most certain first:
//
//   0  the name is exactly what was typed
//   1  a word in the name starts with it  "dior" -> Dior, "marg" -> Margiela
//   2  the name contains it               "miyake"  -> Issey Miyake
//   3  a word is within one or two edits  "givenchi" -> Givenchy
//
// Matching the start of the *first* word was once a tier of its own, above
// matching the start of any later one. That let tier order beat relevance:
// "marg" filled up on Margie Tsai, Margaret Anne and Margit Brandt — whole-name
// prefixes, one show each — and never reached Martin Margiela, whose match is
// on his second word. Which word matched is a far weaker signal than how much
// work the designer has here, so the two are now one tier, ranked by that.
//
// Tier 4 is the only expensive one and only runs when the tiers above have
// not already filled the list, which for ordinary typing is almost always.

const DIACRITICS = /[̀-ͯ]/g;

/** Lowercase, unaccented, punctuation flattened to spaces. */
export function normalise(value) {
  return (value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(DIACRITICS, '')
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Levenshtein distance, abandoned as soon as it is certain to exceed `max`. */
function distance(a, b, max) {
  if (Math.abs(a.length - b.length) > max) return Infinity;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let best = i;
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(
        prev[j] + 1,
        cur[j - 1] + 1,
        prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
      if (cur[j] < best) best = cur[j];
    }
    if (best > max) return Infinity;   // every path is already too long
    prev = cur;
  }
  return prev[b.length] <= max ? prev[b.length] : Infinity;
}

/**
 * Prepare the index once. Normalising 8,657 names on every keystroke is the
 * difference between a search box that keeps up with typing and one that does
 * not.
 */
export function prepare(designers) {
  return (designers || []).map(d => {
    const n = normalise(d.name);
    return { ...d, _n: n, _w: n ? n.split(' ') : [], _e: d.entries || 0 };
  });
}

/**
 * Within a tier, the best match is the designer with the most work in the
 * archive.
 *
 * This used to sort by name length, as a stand-in for relevance, and it
 * failed exactly where it mattered: "Alexa Chung" is shorter than "Alexander
 * McQueen", so typing "alex" offered Alexa Chung, Alexandrine and Alex
 * Mullins and neither McQueen nor Wang. "marg" found four Margarets and no
 * Margiela.
 *
 * Entry counts come from the local show index, so this only became possible
 * once the archive was held locally — before that a count cost a request per
 * designer. Length stays as the tiebreaker for the many designers with one
 * show each, where it is a reasonable guess and nothing better exists.
 */
function byRelevance(a, b) {
  return (b._e - a._e)
    || (a._n.length - b._n.length)
    || a._n.localeCompare(b._n);
}

/** As above, but a whole-name prefix edges out a later-word one on a tie. */
function byRelevanceThenPosition(q) {
  return (a, b) =>
    (b._e - a._e)
    || (b._n.startsWith(q) ? 1 : 0) - (a._n.startsWith(q) ? 1 : 0)
    || (a._n.length - b._n.length)
    || a._n.localeCompare(b._n);
}

/** How many edits to forgive. Short queries match too much to be forgiving. */
function editBudget(query) {
  if (query.length <= 3) return 0;
  if (query.length <= 6) return 1;
  return 2;
}

export function search(index, query, limit = 8) {
  const q = normalise(query);
  if (!q || !index || index.length === 0) return [];

  const tiers = [[], [], []];
  for (const d of index) {
    if (d._n === q) tiers[0].push(d);
    else if (d._w.some(w => w.startsWith(q))) tiers[1].push(d);
    else if (d._n.includes(q)) tiers[2].push(d);
  }

  const out = [];
  const seen = new Set();
  for (const tier of tiers) {
    tier.sort(byRelevanceThenPosition(q));
    for (const d of tier) {
      if (seen.has(d.id)) continue;
      seen.add(d.id);
      out.push(d);
    }
    if (out.length >= limit) return out.slice(0, limit);
  }

  const budget = editBudget(q);
  if (budget === 0) return out.slice(0, limit);

  // Typos almost never change the first letter, and requiring it prunes
  // ~96% of the index before any distance is computed.
  const head = q[0];
  const near = [];
  for (const d of index) {
    if (seen.has(d.id)) continue;
    let bestDist = Infinity;
    let bestWord = 0;
    for (let i = 0; i < d._w.length; i++) {
      const w = d._w[i];
      if (!w || w[0] !== head) continue;
      // Compare against the word, and against its opening of the typed
      // length, so "commes" reaches "comme" in "Comme des Garcons".
      const dist = Math.min(
        distance(q, w, budget),
        distance(q, w.slice(0, q.length + 1), budget),
      );
      if (dist < bestDist) {
        bestDist = dist;
        bestWord = i;
      }
    }
    if (bestDist !== Infinity) near.push({ d, dist: bestDist, word: bestWord });
  }

  // Fewest edits, then how much work the designer has here. Position was
  // once the second key, and "margela" answered with Marcela Daff — one
  // show, but matched on her first word — ahead of Martin Margiela.
  near.sort((a, b) =>
    a.dist - b.dist ||
    byRelevance(a.d, b.d) ||
    a.word - b.word);

  for (const { d } of near) {
    if (seen.has(d.id)) continue;
    seen.add(d.id);
    out.push(d);
    if (out.length >= limit) break;
  }

  return out.slice(0, limit);
}
