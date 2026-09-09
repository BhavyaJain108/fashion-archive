# firstVIEW site structure

Audit of firstview.com as of 2026-09-08, for the adapter in `firstview.py`.

The site is a classic server-rendered PHP app — every view is a GET with
query parameters, nothing is client-rendered, and there is no JSON API.
That makes the whole archive addressable by URL.

## Navigation model

```
collection.php                     browse entry point
   └── collection_results.php      filtered/paginated list of collections
          └── collection_images.php?id={cid}          one show, N looks
                 └── collection_image_closeup.php     one look
                        └── /files/photo_*.jpg        the pixels
```

## 1. Results list — `collection_results.php`

The only endpoint that matters for discovery. All parameters are optional
and combine freely.

| Param | Meaning | Values |
|---|---|---|
| `s_g` | Gender | `Women`, `Men` |
| `filter_year` | Year | `1989`–`2027` (39 years) |
| `filter_season` | Season | `1` Fall/Winter · `2` Spring/Summer · `3` Cruise · `5` Prefall |
| `s_t` | Shoot type | `7` Runway Collection · `4` Runway Details · `11` Runway Atmosphere · `3` Backstage Beauty and Fashion · `8` Lookbook · `5` Bridal Collection |
| `s_n` | Category | `1` Ready-to-Wear · `2` Haute Couture · `3` Swim |
| `s_p` | City | 37 cities, see below |
| `l` | Designer initial | `A`–`Z` |
| `b` | Sort | `date` |
| `page` | Page number | 0-based, **20 results per page** |
| `clear` | Reset filters | `1` |

**Result rows** are `div.collectTitle`, each containing a link to
`collection_images.php?id={cid}` with text in the form:

```
{Designer} - {Season} {Year} - {Gender}
{Designer} - {Year} - {Gender}            season omitted, e.g. Victoria's Secret
```

so designer, season, year and gender are parseable from the list page
without opening the show. Season is optional — treat a missing one as
data, not a parse failure.

### Cities (`s_p`)

`1` Paris · `2` New York · `3` Beijing · `4` Sydney · `5` Moscow ·
`6` Los Angeles · `7` Sao Paulo · `8` Milan · `9` Barcelona ·
`11` Kuala Lumpur · `12` Melbourne · `13` Seoul · `14` Auckland ·
`15` London · `16` Madrid · `17` Hong Kong · `18` Tokyo ·
`19` Rio De Janeiro · `20` Bali · `21` Berlin · `22` Mexico City ·
`23` Miami · `24` Florence · `26` India · `29` Singapore ·
`30` Bangkok · `31` Amsterdam · `32` Copenhagen · `33` Belo Horizonte ·
`34` Stockholm · `35` Rome · `36` Toronto · `37` Valencia ·
`38` Muscat · `42` Lisbon · `53` Gran Canaria · `54` Nairobi

Note the gaps — ids are not contiguous, so always read them from the
`select` rather than generating a range.

## 2. One show — `collection_images.php?id={cid}`

| Param | Meaning |
|---|---|
| `id` | Collection id |
| `list=all` | **Required.** Show every look; without it you get only the first 20 |
| `p` | Page number when not using `list=all` |
| `jumpto={image_id}` | Scroll anchor, pairs with `#a{image_id}` |

Each look is a `div.thumbnailjt` containing:

- `img.picture` — `src=/files/photo_thumbnail_{image_id}.jpg`
- `a[href]` — `collection_image_closeup.php?of={index}&collection={cid}&image={image_id}`
- `a.pictureinfo[data-content]` — `<br>`-separated popover:
  `designer`, `category`, `gender`, `season`

Collection-level season also appears in an element with `class="season"`.

## 3. One look — `collection_image_closeup.php`

Params `of` (0-based look index), `collection`, `image`. Serves
`/files/photo_mid_def_{image_id}.jpg`.

## 4. Image assets — two schemes

A collection uses one scheme or the other. **This is not determined by the
show's year** — 1989 Versace (52962) is hashed, 2015 Agnes b (41763) is
legacy. Detect per collection, never infer from the date. Both appear on
the collection page, so **neither needs the closeup pages**: one request
per show yields every URL at both sizes.

### Legacy — e.g. collection 50990

| Pattern | Size |
|---|---|
| `/files/photo_thumbnail_{image_id}.jpg` | small |
| `/files/photo_mid_def_{image_id}.jpg` | 423 × 634, ~75 KB |

Derivable from the image id alone.

### Hashed — e.g. collection 53365

| Pattern | Size |
|---|---|
| `/files/{cid}/thumb_{image_id}-{hash}.jpg` | small |
| `/files/{cid}/{image_id}-{hash}.jpg` | **567 × 850**, ~200 KB |

The `{hash}` is opaque and **cannot be guessed from an image id** — but it
is identical across both sizes, so the large URL is just the thumbnail URL
with its `thumb_` prefix removed. Read it off the collection page.

Newer collections therefore carry ~1.8× the pixels of legacy ones. Where a
show exists in the hashed scheme, that is the best size available without
an account.

### Above these sizes

The closeup image is wrapped in `<a href="javascript:;">` and the page's
scripts route to `openlogin()` / `fv_login()`, so anything larger than the
sizes above sits behind an account — presumably the subscription firstVIEW
sells. That is an access question to settle with them, not a parsing one.

## Designers

`alpha_list.php?type=designer&l={A-Z}&deslist=1` lists designers for a
letter, each linking to `collection_designer.php?s_d={designer_id}`.
Counts vary widely: A 836 (includes numeric/symbol names), B 391, Z 82,
Q 13. No pagination observed on these — one letter, one page.

`collection_designer.php?s_d={id}` returns every show by that designer
across all years and genders, **paginated with `page` at 20 rows**.
Balenciaga (`s_d=156`) is 124 shows over 7 pages; reading page 0 only
gives 20 and looks complete.

One show can span several collection ids — Issey Miyake FW2025 Men is
56512 and 56513. A collection id is not a show.

## Shoot types

Page-1 counts for 2019 Women: Runway Collection 20, Runway Details 20,
Backstage 18, Bridal 20, Lookbook 1, **Runway Atmosphere 0** — atmosphere
lives at `collection_atmosphere_results.php`, not behind `s_t=11`.

## Other sections (not yet mapped)
- `slideshow.php?type=collection&id={cid}` — slideshow view of a show
- `collection_videos_designers.php` — video content
- `collection_atmosphere_results.php` — atmosphere shoots
- `streetstyle.php` — street style

## Access notes

`robots.txt` disallows `*` and allows only Googlebot, Slurp and msnbot, so
this adapter exists on the strength of direct permission from the rights
holder for **personal** use. Practical consequences, enforced in
`firstview.py`:

- Gentle by default: 3 workers, 0.5 s delay, re-runs skip cached files.
- Only the two resolutions the site itself serves are requested; no
  probing for undisclosed assets.
- Provenance is written next to every download (`collection.json`).

Personal use does not cover redistribution. Serving these images from a
public deployment is a separate permission worth getting in writing first.

## Coverage catalog

`coverage.json` records which year x season x gender combinations have
shows — 169 of 312 do, so 143 filter combinations are dead ends. Built by
`firstview.build_coverage` (~880 requests, ~8 min) and committed, because
`cache/` is gitignored and the file would otherwise never reach a deploy.

Counts are page-0 counts and saturate at 20: they mean "at least this
many", and only 0 is exact. If the file is missing every option stays
selectable, which is the safe direction — a dead end beats hiding shows.
Rebuild when a season is added.
