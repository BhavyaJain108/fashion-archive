import React, { useState } from 'react';

// What every word on the deck means, in one place, folded away until asked for.
// Written for the person reading the page, not for the code: each entry says what
// the number is, where it comes from, and what a good or bad value looks like.
const TERMS = [
  ['State', 'Where a brand is in its life. new → scoped (probed, plan written) → calibrating (first sample) → active (scraping on schedule). degraded means the last run finished with reservations; needs_attention means no plan works and a person should look; gated means the shop is behind a password; unreachable means the run crashed.'],
  ['Products', 'How many products the public site shows for the brand right now — those seen in the last run that earned coverage.'],
  ['Gate', 'Pass or fail on six fields a shop cannot sell without: link, title, price, stock, main photo, photos. A brand passes if each is missing on 1% of products or fewer; the odd unphotographed item is the shop’s choice, not our failure.'],
  ['Fields', 'The share of the 42 E0005 fields carrying a value, averaged over the brand’s products. 25% is typical from a shop’s feed alone; the finder raises it by learning rules for the rest.'],
  ['s / product', 'Wall-clock seconds per product in the last run, including photographs. 0.3–1.0 is normal over HTTP; a browser brand runs at 3 or more.'],
  ['$ run', 'What the last run spent on the model (the finder). Zero unless rules were learned.'],
  ['Next', 'When the schedule next wants the brand. “due now” means a worker will take it on its next ten-second poll.'],
  ['Needs a human', 'How many runs in a row ended needing a person, and why. After three, the brand is looked at less often (doubling up to 16× its cadence) but never dropped.'],
  ['Next action', 'The top line of what the archive recommends after the last run, ranked: a failed gate first, then a field holding the wrong thing, then a blocked host, then fields never searched, then dead ends, then cost.'],
  ['Composition', 'The plan, written transport × discovery × fetch × change signal. Transport is how we connect (t0 plain HTTP, t1 a browser’s handshake without a browser, t2 a real browser, t4 password-gated). Discovery is where the list of products comes from (a bulk feed, a store API, the sitemap). Fetch is where one product’s data comes from. Change signal is how we tell a product changed.'],
  ['Tried and failed', 'Compositions that failed for this brand, with when and why. A failure keeps its rung off the ladder for seven days, then it is offered again.'],
  ['Class (A–H)', 'What kind of field it is. A guaranteed by the sale (a blank is our bug). B editorial (published when the brand bothers). C variant structure (sizes, availability). D derived (computed, never extracted). E codes (with their type). F taxonomy (a category path). G not applicable to apparel. H the brand’s own tags.'],
  ['Fill', 'For one field, the share of products carrying it, from the last scorecard.'],
  ['Rules', 'Learned rules for the field: how to read it off the product page, and how often each fired. A rule firing on a few percent beside a sibling at sixty was learned from one page’s accident and is ranked behind it.'],
  ['Searched', 'Where the archive looked for a blank field: the channel (feed or API), the learned rules, a rendered page, the model. “Absent from” every source is a fact about the brand; “never searched” is a gap in our work; “channel only” means nobody has read the page for it yet.'],
  ['Verdict (runs)', 'ok: coverage at least 95% and every title present. degraded: finished but short of that, or the finder could not run. failed: under 60% coverage, nothing stored, or the channel reported no products. lost: the worker was replaced before the run finished.'],
  ['Stored', 'Products the run wrote to the catalogue. “—” means the run never reached it.'],
  ['Took', 'Start to finish, including the photographs pass.'],
  ['Hosts', 'How the brand’s servers answered over the last week: requests, OK, refused (401/403 — a bot verdict, needs a different transport), slow down (429/503), errored, and average latency.'],
  ['Progress bar', 'The phase a running scrape is in and how far along: fetching products, finalising, then photographs. Updated every twenty seconds.'],
  ['Finder', 'The one part that costs money: a model reads a product page and proposes rules for the fields still blank. A rule is kept only if replaying it on that page reproduces the value. Capped per day across the fleet; a field it could not find is left for fourteen days, then tried again.'],
];

export default function DevGlossary() {
  const [open, setOpen] = useState(false);
  return (
    <div className="dev-glossary">
      <button type="button" className="dev-link dev-domain" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} what am I reading
      </button>
      {open && (
        <table className="dev-table">
          <tbody>
            {TERMS.map(([k, v]) => (
              <tr key={k}>
                <td className="key">{k}</td>
                <td className="wrap">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
