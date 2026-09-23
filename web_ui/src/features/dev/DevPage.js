import React from 'react';

import DevOverview from './DevOverview';
import DevBrand from './DevBrand';
import DevProducts from './DevProducts';
import DevCosts from './DevCosts';
import DevNotes from './DevNotes';
import './DevPage.css';

// The machine room. Four views, one frame. Which view is a fact about the URL
// (see routes.js), and every move between them is a navigation, so Back works
// and a brand's page can be linked to.
//
// The deck reads; the daemon writes. The only things a button here changes are
// two fields on a brand's schedule row — the same object the daemon has always
// been steered by — so there is no second control path to keep in step.
export default function DevPage({ route, navigate }) {
  const go = (r) => navigate({ page: 'dev', ...r });

  let view = 'overview';
  if (route.brandId && route.category === 'products') view = 'products';
  else if (route.brandId) view = 'brand';
  else if (route.category === 'costs') view = 'costs';

  return (
    <div className="dev-frame ar-scroll">
    <div className="dev">
      <nav className="dev-nav" aria-label="Machine room">
        <span className="dev-wordmark">Machine room</span>
        <button
          type="button"
          className={`dev-nav-item${view === 'overview' ? ' selected' : ''}`}
          aria-pressed={view === 'overview'}
          onClick={() => go({})}
        >
          Brands
        </button>
        <button
          type="button"
          className={`dev-nav-item${view === 'costs' ? ' selected' : ''}`}
          aria-pressed={view === 'costs'}
          onClick={() => go({ category: 'costs' })}
        >
          Costs
        </button>
        {route.brandId && (
          <span className="dev-crumb">
            <span aria-hidden="true">/</span>{' '}
            {view === 'products' ? (
              <>
                <button type="button" className="dev-link" onClick={() => go({ brandId: route.brandId })}>
                  {route.brandId}
                </button>{' '}
                <span aria-hidden="true">/</span> catalogue
              </>
            ) : (
              route.brandId
            )}
          </span>
        )}
        {/* The one way out of the machine room, through the app's own router like
            every other page switch. */}
        <button type="button" className="dev-nav-item dev-nav-exit" onClick={() => navigate({ page: 'brands' })}>
          ← site
        </button>
      </nav>

      <div className="dev-layout">
        <main className="dev-main">
          {view === 'overview' && <DevOverview go={go} />}
          {view === 'costs' && <DevCosts />}
          {view === 'brand' && <DevBrand domain={route.brandId} go={go} />}
          {view === 'products' && <DevProducts domain={route.brandId} run={route.token} go={go} />}
        </main>
        <DevNotes />
      </div>
    </div>
    </div>
  );
}
