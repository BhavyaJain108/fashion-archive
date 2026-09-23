import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import DevPage from './DevPage';
import DevEndpoints from '../../shared/api/dev';

// The API is stubbed at the endpoint layer, so these prove the views render what
// the server sends and that the two controls call the right command — nothing
// about the network.
jest.mock('../../shared/api/dev');

const overview = {
  success: true,
  generated_at: new Date().toISOString(),
  totals: { brands: 2, showing: 1, live_products: 381, photographs: 1200, need_a_human: 1, failed_gate: 0 },
  workers: { running: [], stalled: [] },
  finder: { day: '2026-09-22', usd: 0.4, calls: 3, cap_usd: 2, history: {} },
  brands: [
    {
      domain: 'huelleyrose.com', name: 'Huelley Rose', live_products: 381, photographs: 1200,
      state: 'active', enabled: true, claimed_by: null, worker_alive: null,
      next_due: new Date(Date.now() + 3600000).toISOString(), last_run: new Date().toISOString(),
      gate: true, fields_filled: 0.27, seconds_per_product: 0.5, cost_usd: 0,
      attention_streak: 0, next_action: 'all_images missing on 1 of 381 products',
    },
    {
      domain: 'laluneofficial.com', name: 'La Lune', live_products: 0, photographs: 0,
      state: 'needs_attention', enabled: true, claimed_by: null, worker_alive: null,
      next_due: null, last_run: null, gate: null, fields_filled: null,
      attention_streak: 3, attention_reason: 'no lane: nothing readable at any transport',
      empty_because: 'the last run could not reach it',
    },
  ],
};

const brand = {
  success: true,
  generated_at: new Date().toISOString(),
  brand: { ...overview.brands[0], cadence_seconds: 86400 },
  plan: {
    composition: 't0×bulk_json×platform_json×per_item', transport: 't0', discovery: 'bulk_json',
    fetch: 'platform_json', change_signal: 'per_item', status: 'ready', stale: false,
    fingerprinted_at: new Date().toISOString(), sitemap_url: null, product_url_prefix: '/products/',
    currency: 'USD', tried: [],
  },
  runs: [
    {
      id: 'r1', mode: 'delta', started_at: new Date(Date.now() - 600000).toISOString(), finished_at: new Date().toISOString(),
      exit_status: 0, coverage: { verdict: 'ok', extracted: 381, coverage_pct: 1, reasons: [] },
      card: { run_id: 'r1', scored_at: new Date().toISOString(), products: 381, required_ok: true, required_gaps: { all_images: 0.0026 }, fields_filled: 0.27, images_per_product: 5.5, seconds_per_product: 0.5, cost_usd: 0 },
    },
    {
      id: 'r0', mode: 'delta', started_at: new Date(Date.now() - 90000000).toISOString(), finished_at: new Date(Date.now() - 89990000).toISOString(),
      exit_status: 1, coverage: null, card: null,
    },
  ],
  fields: [
    { name: 'product_title', class: 'A', fill: 1, evidence: 'channel only — the page has not been read for this field', rules: [] },
    { name: 'size_info', class: 'C', fill: 0.98, evidence: 'absent from channel', rules: [{ kind: 'css_all_attr', expression: '[data-size]', hits: 372 }] },
  ],
  classes: { A: ['guaranteed by the sale', 'must be 100%'], C: ['variant structure', 'labels public'] },
  recipe_book: { learned_at: new Date().toISOString(), learned_from_url: 'https://x', rendered: false, rules: 1 },
  recommendations: { run_id: 'r1', at: new Date().toISOString(), findings: [{ priority: 5, headline: 'all_images missing on 1 of 381 products', action: 'within the gate\'s tolerance' }] },
  hosts: [],
};

beforeEach(() => {
  DevEndpoints.getNotes.mockResolvedValue({ success: true, notes: [{ id: '1', text: 'sort by cost', at: new Date().toISOString(), done: false }] });
  DevEndpoints.addNote.mockResolvedValue({ success: true });
  DevEndpoints.addBrand.mockResolvedValue({ success: true, domain: 'new.com', name: 'New', shown: true, already_scheduled: false });
  DevEndpoints.getOverview.mockResolvedValue(overview);
  DevEndpoints.getBrand.mockResolvedValue(brand);
  DevEndpoints.getHosts.mockResolvedValue({ success: true, domain: 'huelleyrose.com', days: 7, hosts: [] });
  DevEndpoints.getChanges.mockResolvedValue({ success: true, domain: 'huelleyrose.com', changes: [] });
  DevEndpoints.getRunLog.mockResolvedValue({
    success: true, domain: 'huelleyrose.com', run_id: 'r0',
    events: [
      { t: '2026-09-21T05:00:00+00:00', event: 'planned', composition: 't0×bulk_json×platform_json×per_item', status: 'ready' },
      { t: '2026-09-21T05:00:02+00:00', event: 'channel-busy', reason: '429 from huelleyrose.com' },
    ],
  });
  DevEndpoints.runNow.mockResolvedValue({ success: true });
  DevEndpoints.pause.mockResolvedValue({ success: true });
});

test('the overview shows every brand with its gate and what needs a human', async () => {
  render(<DevPage route={{ page: 'dev', brandId: null, category: null }} navigate={() => {}} />);
  expect(await screen.findByText('Huelley Rose')).toBeInTheDocument();
  expect(screen.getByText(/needs a human · 3 runs/)).toBeInTheDocument();
  expect(screen.getByText(/next: all_images missing on 1 of 381/)).toBeInTheDocument();
  expect(screen.getAllByText('pass').length).toBeGreaterThan(0);
});

test('run now and pause are commands on the schedule, then a reload', async () => {
  render(<DevPage route={{ page: 'dev', brandId: null, category: null }} navigate={() => {}} />);
  await screen.findByText('Huelley Rose');
  fireEvent.click(screen.getAllByRole('button', { name: 'run now' })[0]);
  await waitFor(() => expect(DevEndpoints.runNow).toHaveBeenCalledWith('huelleyrose.com'));
  // Both controls on a row are held while a command is in flight; wait for the
  // row to come back before pressing the other one.
  const pause = screen.getAllByRole('button', { name: 'pause' })[0];
  await waitFor(() => expect(pause).not.toBeDisabled());
  fireEvent.click(pause);
  await waitFor(() => expect(DevEndpoints.pause).toHaveBeenCalledWith('huelleyrose.com'));
  expect(DevEndpoints.getOverview.mock.calls.length).toBeGreaterThanOrEqual(3);
});

test('columns sort, and a selection runs as one batch', async () => {
  DevEndpoints.batch.mockResolvedValue({ success: true, action: 'run', results: { 'huelleyrose.com': 'queued', 'laluneofficial.com': 'queued' } });
  render(<DevPage route={{ page: 'dev', brandId: null, category: null }} navigate={() => {}} />);
  await screen.findByText('Huelley Rose');
  const names = () => screen.getAllByRole('button', { name: /Huelley Rose|La Lune/ }).map((b) => b.textContent);
  expect(names()[0]).toBe('Huelley Rose');
  fireEvent.click(screen.getByRole('button', { name: /^Products/ }));
  expect(names()[0]).toBe('La Lune'); // 0 products sorts first, ascending
  fireEvent.click(screen.getByRole('button', { name: /^Products/ }));
  expect(names()[0]).toBe('Huelley Rose');

  fireEvent.click(screen.getByRole('checkbox', { name: 'Select every brand shown' }));
  fireEvent.click(screen.getByRole('button', { name: 'run selected' }));
  await waitFor(() => expect(DevEndpoints.batch).toHaveBeenCalledWith('run', expect.arrayContaining(['huelleyrose.com', 'laluneofficial.com'])));
  expect(await screen.findByText('2 queued')).toBeInTheDocument();
});

test('notes sit beside every view and a brand can be added from the overview', async () => {
  render(<DevPage route={{ page: 'dev', brandId: null, category: null }} navigate={() => {}} />);
  expect(await screen.findByText('sort by cost')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('New note'), { target: { value: 'show cost per product' } });
  fireEvent.click(screen.getByRole('button', { name: 'add note' }));
  await waitFor(() => expect(DevEndpoints.addNote).toHaveBeenCalledWith('show cost per product'));

  fireEvent.click(await screen.findByRole('button', { name: 'add a brand' }));
  fireEvent.change(screen.getByLabelText('Domain'), { target: { value: 'https://New.com/shop' } });
  fireEvent.click(screen.getByRole('button', { name: 'add and scrape now' }));
  await waitFor(() => expect(DevEndpoints.addBrand).toHaveBeenCalledWith('new.com', '', true));
  expect(await screen.findByText(/New added and due now/)).toBeInTheDocument();
});

test('a brand name is a navigation, not a fetch', async () => {
  const navigate = jest.fn();
  render(<DevPage route={{ page: 'dev', brandId: null, category: null }} navigate={navigate} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Huelley Rose' }));
  expect(navigate).toHaveBeenCalledWith({ page: 'dev', brandId: 'huelleyrose.com' });
});

test('the brand page lists fields with class, fill, rules and where we searched', async () => {
  render(<DevPage route={{ page: 'dev', brandId: 'huelleyrose.com', category: null }} navigate={() => {}} />);
  expect(await screen.findByText('t0×bulk_json×platform_json×per_item')).toBeInTheDocument();
  expect(screen.getByText('size_info')).toBeInTheDocument();
  expect(screen.getByText(/fired 372/)).toBeInTheDocument();
  expect(screen.getByText(/absent from channel/)).toBeInTheDocument();
  expect(screen.getByText('all_images missing on 1 of 381 products')).toBeInTheDocument();
});

test('a learn run is queued from the brand page and reads as what it learned', async () => {
  DevEndpoints.learn.mockResolvedValue({ success: true, outcome: 'queued', mode: 'learn' });
  DevEndpoints.getBrand.mockResolvedValue({
    ...brand,
    runs: [
      { id: 'r2', mode: 'learn', started_at: new Date().toISOString(), finished_at: new Date().toISOString(),
        exit_status: 0, coverage: null, card: null, pages: 12, rules: 3, fields_gained: ['material_info', 'care'] },
      ...brand.runs,
    ],
  });
  render(<DevPage route={{ page: 'dev', brandId: 'huelleyrose.com', category: null }} navigate={() => {}} />);
  await screen.findByText('t0×bulk_json×platform_json×per_item');
  expect(screen.getByText(/learned · 3 rules from 12 pages · 2 new fields/)).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('retry searched fields'));
  fireEvent.click(screen.getByRole('button', { name: 'learn fields' }));
  await waitFor(() => expect(DevEndpoints.learn).toHaveBeenCalledWith('huelleyrose.com', true));
});

test('every run is listed, and an unscored one opens its log', async () => {
  render(<DevPage route={{ page: 'dev', brandId: 'huelleyrose.com', category: null }} navigate={() => {}} />);
  await screen.findByText('t0×bulk_json×platform_json×per_item');
  expect(screen.getByText(/degraded · no catalogue/)).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole('button', { name: 'log' })[1]);
  expect(await screen.findByText('channel-busy')).toBeInTheDocument();
  expect(DevEndpoints.getRunLog).toHaveBeenCalledWith('huelleyrose.com', 'r0');
});

test('a held brand shows where its scrape is, as a bar with the phase in words', async () => {
  DevEndpoints.getOverview.mockResolvedValue({
    ...overview,
    workers: { running: ['huelleyrose.com'], stalled: [] },
    brands: [{ ...overview.brands[0], claimed_by: 'worker-1', worker_alive: true, claimed_at: new Date().toISOString(),
      progress: { phase: 'fetching', done: 120, total: 381, updated_at: new Date().toISOString() } }],
  });
  render(<DevPage route={{ page: 'dev', brandId: null, category: null }} navigate={() => {}} />);
  const bars = await screen.findAllByRole('status');
  expect(bars.length).toBeGreaterThan(0);
  expect(screen.getAllByText('reading products').length).toBeGreaterThan(0);
  expect(screen.getAllByText(/120 \/ 381 · 31%/).length).toBeGreaterThan(0);
  // While a worker holds it, run now is off and pause says when it lands.
  expect(screen.getByRole('button', { name: 'run now' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'pause after run' })).toBeEnabled();
});

test('a dead worker offers release; a paused brand offers one run', async () => {
  DevEndpoints.release.mockResolvedValue({ success: true, released: true });
  DevEndpoints.getOverview.mockResolvedValue({
    ...overview,
    workers: { running: [], stalled: ['huelleyrose.com'] },
    brands: [
      { ...overview.brands[0], claimed_by: 'worker-1', worker_alive: false, claimed_at: new Date(Date.now() - 20 * 60000).toISOString() },
      { ...overview.brands[1], enabled: false, run_once: false },
    ],
  });
  render(<DevPage route={{ page: 'dev', brandId: null, category: null }} navigate={() => {}} />);
  await screen.findByText('Huelley Rose');
  fireEvent.click(screen.getByRole('button', { name: 'release' }));
  await waitFor(() => expect(DevEndpoints.release).toHaveBeenCalledWith('huelleyrose.com'));
  expect(screen.getByText('paused')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'run once' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'resume' })).toBeEnabled();
});

test('the catalogue offers the brand\'s own facets and a chip narrows the page', async () => {
  DevEndpoints.getProducts.mockResolvedValue({
    success: true, domain: 'huelleyrose.com', total: 2, offset: 0, run: null, status: 'live', runs: [],
    facets: {
      colour: [{ value: 'Black', count: 2, selected: false }, { value: 'Red', count: 1, selected: false }],
      size: [{ value: 'S', count: 2, selected: false, in_stock: 1 }, { value: 'M', count: 1, selected: false, in_stock: 1 }],
    },
    selected: {}, sized_in_stock: false, price_range: { min: 80, max: 200 }, price_min: null, price_max: null,
    products: [
      { itemurl: 'https://huelleyrose.com/p/1', product_title: 'Coat', price: 200, currency: 'USD', images: [], size_info: 'S, M', color_info: 'Black' },
      { itemurl: 'https://huelleyrose.com/p/2', product_title: 'Top', price: 80, currency: 'USD', images: [], size_info: 'S', color_info: 'Red' },
    ],
  });
  render(<DevPage route={{ page: 'dev', brandId: 'huelleyrose.com', category: 'products', token: null }} navigate={() => {}} />);
  expect(await screen.findByRole('group', { name: 'colour' })).toBeInTheDocument();
  expect(screen.getByText(/1 in stock/)).toBeInTheDocument(); // S: 2 offered, 1 in stock
  fireEvent.click(screen.getByRole('button', { name: /^Black/ }));
  await waitFor(() => expect(DevEndpoints.getProducts).toHaveBeenLastCalledWith(
    'huelleyrose.com', expect.objectContaining({ filters: { colour: ['Black'] } }),
  ));
  expect(screen.getByRole('button', { name: 'clear filters' })).toBeInTheDocument();
});

test('someone who is not the owner sees a plain notice', async () => {
  DevEndpoints.getOverview.mockResolvedValue({ forbidden: true });
  render(<DevPage route={{ page: 'dev', brandId: null, category: null }} navigate={() => {}} />);
  expect(await screen.findByText(/for the archive’s owner/)).toBeInTheDocument();
});
