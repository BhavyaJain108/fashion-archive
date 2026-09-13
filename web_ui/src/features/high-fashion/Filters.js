import React from 'react';

// Garment category — firstVIEW's `s_n` filter. Optional, like every filter
// but gender: left unset, Ready-to-Wear, Couture and Swim all appear, and
// each row says which it is.
//
// Exported because the page derives `categoriesAvailable` from it: the list
// of categories the archive could offer and the list it does offer have to
// be the same list.
export const GARMENT_TYPES = [
  { value: 'Ready-to-Wear', label: 'Ready-to-Wear' },
  { value: 'Haute Couture', label: 'Haute Couture' },
  { value: 'Swim', label: 'Swim' },
];

// Shoot type — firstVIEW's `s_t`. One show is catalogued several times, once
// per shoot, which is why the list used to look full of duplicates. They are
// genuinely different shoots of the same show, so the fix is to label them —
// the shoot type rides in each row's subtext — rather than to hide all but
// one, which is what forcing a single choice here amounted to.
const SHOOT_TYPES = [
  { value: 'Runway Collection', label: 'Collection' },
  { value: 'Runway Details', label: 'Details' },
  { value: 'Runway Atmosphere', label: 'Atmosphere' },
  { value: 'Backstage Beauty and Fashion', label: 'Backstage' },
  { value: 'Lookbook', label: 'Lookbook' },
  { value: 'Bridal Collection', label: 'Bridal' },
];

// Seasons are shown abbreviated: the subtext carries five other fields.
const SEASON_LABELS = {
  'Fall / Winter': 'F/W',
  'Spring / Summer': 'S/S',
};

// Jumping by initial is the only way firstVIEW offers to reach a designer
// directly, and with the whole archive in one list it is the difference
// between finding Yohji Yamamoto and scrolling for a very long time.
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

// The search box and the facet rows at the top of the sidebar.
//
// Presentational: every value and every handler is a prop. The state these
// read and write still lives in HighFashionPage, deliberately — this task
// moved the markup and nothing else.
function Filters({
  // Search
  searchInputRef,
  designerIndex,
  query,
  setQuery,
  searchFocused,
  setSearchFocused,
  handleSearchKeyDown,
  suggestionList,
  activeSuggestion,
  setActiveSuggestion,
  chooseSuggestion,
  // Facets
  indexReady,
  designerMode,
  filters,
  setFilter,
  years,
  designerYears,
  seasonsAvailable,
  designerSeasons,
  categoriesAvailable,
  designerCategories,
  designerShootTypes,
  facetValues,
  facetCount,
  clearFilters,
  activeFilterCount,
}) {
  return (
    <>
        {/* Search. One box: type a designer, press Enter, get everything they
            ever showed. The archive list is organised by season, so a
            designer's own history across thirty years is the one view the
            filters below cannot produce at all. */}
        <div className="hf2-search">
          <input
            ref={searchInputRef}
            type="text"
            className="hf2-search-input"
            placeholder={!designerIndex ? 'Search unavailable'
                         : indexReady ? 'Search designers and shows'
                         : 'Search designers'}
            value={query}
            disabled={!designerIndex}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setSearchFocused(true)}
            // A click on a suggestion blurs the input first, so closing is
            // deferred a beat or the option is gone before it is chosen.
            onBlur={() => setTimeout(() => setSearchFocused(false), 120)}
            onKeyDown={handleSearchKeyDown}
            spellCheck={false}
            autoComplete="off"
          />
          {query && (
            <button type="button" className="hf2-search-clear"
                    onClick={() => { setQuery(''); searchInputRef.current?.focus(); }}>
              ✕
            </button>
          )}

          {searchFocused && suggestionList.length > 0 && (
            <div className="hf2-search-results">
              {!query.trim() && (
                <div className="hf2-search-heading">Recently opened</div>
              )}
              {suggestionList.map((item, i) => {
                const active = i === activeSuggestion ? 'active' : '';
                // `key` stays off this object: React warns when a key is
                // spread in with the rest of the props, because it is not a
                // prop — it is how the list is reconciled.
                const common = {
                  type: 'button',
                  onMouseEnter: () => setActiveSuggestion(i),
                  onMouseDown: (e) => e.preventDefault(),
                  onClick: () => chooseSuggestion(item),
                };
                if (item.kind === 'designer') {
                  return (
                    <button key={item.key} {...common} className={`hf2-search-option ${active}`}>
                      <span className="label">{item.designer.name}</span>
                      {/* Exact, from the local index. Entries rather than
                          shows: a show is listed once per shoot. */}
                      {item.designer.entries > 0 && (
                        <span className="meta">{item.designer.entries}</span>
                      )}
                    </button>
                  );
                }
                if (item.kind === 'show') {
                  return (
                    <button key={item.key} {...common} className={`hf2-search-option show ${active}`}>
                      <span className="label">{item.show.designer}</span>
                      <span className="sub">{item.show.subtitle}</span>
                    </button>
                  );
                }
                return (
                  <button key={item.key} {...common} className={`hf2-search-option all ${active}`}>
                    <span className="label">All {item.total} matching shows</span>
                  </button>
                );
              })}
            </div>
          )}
          {searchFocused && query.trim() && suggestionList.length === 0 && (
            <div className="hf2-search-results">
              <div className="hf2-search-empty">Nothing matches that</div>
            </div>
          )}
        </div>

        {/* Filters. Every one of them is optional and additive: the list
            below starts as the whole archive and each choice narrows it.
            One thin row per filter, left aligned, so five of them cost less
            height than a single scroll wheel did. */}
        <div className="hf2-filters">
          {/* Gender is the one filter the archive list cannot leave empty:
              firstVIEW has no "both", and a query without a gender returns a
              small bucket of ungendered shows rather than everything.
              In designer mode that constraint is gone — both genders are
              already loaded — so All appears and is the default. */}
          <div className="hf2-segmented">
            {((designerMode || indexReady) ? ['', 'Women', 'Men'] : ['Women', 'Men']).map(g => (
              <button
                key={g || 'all'}
                type="button"
                className={`hf2-segment ${g === filters.gender ? 'selected' : ''}`}
                onClick={() => setFilter('gender', g)}
              >{g || 'All'}</button>
            ))}
          </div>

          <label className="hf2-facet">
            <span className="hf2-facet-label">Year</span>
            <select
              className={`hf2-facet-select ${filters.year ? 'set' : ''}`}
              value={filters.year}
              onChange={(e) => setFilter('year', e.target.value)}
            >
              <option value="">All years</option>
              {(designerYears || years).map(y => (
                <option key={y} value={y}>
                  {y}{facetCount('year', y) ? ` (${facetCount('year', y)})` : ''}
                </option>
              ))}
            </select>
          </label>

          <label className="hf2-facet">
            <span className="hf2-facet-label">Season</span>
            <select
              className={`hf2-facet-select ${filters.season ? 'set' : ''}`}
              value={filters.season}
              onChange={(e) => setFilter('season', e.target.value)}
            >
              <option value="">All seasons</option>
              {(designerSeasons || seasonsAvailable).map(sn => (
                <option key={sn} value={sn}>{SEASON_LABELS[sn] || sn}</option>
              ))}
            </select>
          </label>

          <label className="hf2-facet">
            <span className="hf2-facet-label">Type</span>
            <select
              className={`hf2-facet-select ${filters.category ? 'set' : ''}`}
              value={filters.category}
              onChange={(e) => setFilter('category', e.target.value)}
            >
              <option value="">All types</option>
              {GARMENT_TYPES.filter(t => (designerCategories || categoriesAvailable)
                                             .includes(t.value)).map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>

          <label className="hf2-facet">
            <span className="hf2-facet-label">Shoot</span>
            <select
              className={`hf2-facet-select ${filters.shootType ? 'set' : ''}`}
              value={filters.shootType}
              onChange={(e) => setFilter('shootType', e.target.value)}
            >
              <option value="">All shoots</option>
              {SHOOT_TYPES.filter(t => !designerShootTypes
                                       || designerShootTypes.includes(t.value)).map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>

          {/* City. The index has known this all along — it is on every row —
              but it took holding the archive to be able to offer it without
              a crawl per option. */}
          <label className={`hf2-facet ${indexReady ? '' : 'hidden'}`}>
            <span className="hf2-facet-label">City</span>
            <select
              className={`hf2-facet-select ${filters.city ? 'set' : ''}`}
              value={filters.city}
              onChange={(e) => setFilter('city', e.target.value)}
            >
              <option value="">All cities</option>
              {(facetValues('city') || []).map(c => (
                <option key={c} value={c}>
                  {c}{facetCount('city', c) ? ` (${facetCount('city', c)})` : ''}
                </option>
              ))}
            </select>
          </label>

          <label className={`hf2-facet ${designerMode ? 'hidden' : ''}`}>
            <span className="hf2-facet-label">Brand</span>
            <select
              className={`hf2-facet-select ${filters.letter ? 'set' : ''}`}
              value={filters.letter}
              onChange={(e) => setFilter('letter', e.target.value)}
            >
              <option value="">A–Z</option>
              {LETTERS.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>

          <button
            type="button"
            className="hf2-filter-clear"
            onClick={clearFilters}
            disabled={activeFilterCount === 0}
          >
            {activeFilterCount === 0
              ? 'Whole archive'
              : `Clear ${activeFilterCount} filter${activeFilterCount > 1 ? 's' : ''}`}
          </button>
        </div>
    </>
  );
}

export default Filters;
