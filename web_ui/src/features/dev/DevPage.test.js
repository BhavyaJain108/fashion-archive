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
  DevEndpoints.getOverview.mockResolvedValue(overview);
  DevEndpoints.getBrand.mockResolvedValue(brand);
  DevEndpoints.getHosts.mockResolvedValue({ success: true, domain: 'huelleyrose.com', days: 7, hosts: [] });
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

test('every run is listed, and an unscored one opens its log', async () => {
  render(<DevPage route={{ page: 'dev', brandId: 'huelleyrose.com', category: null }} navigate={() => {}} />);
  await screen.findByText('t0×bulk_json×platform_json×per_item');
  expect(screen.getByText(/degraded · no catalogue/)).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole('button', { name: 'log' })[1]);
  expect(await screen.findByText('channel-busy')).toBeInTheDocument();
  expect(DevEndpoints.getRunLog).toHaveBeenCalledWith('huelleyrose.com', 'r0');
});

test('someone who is not the owner sees a plain notice', async () => {
  DevEndpoints.getOverview.mockResolvedValue({ forbidden: true });
  render(<DevPage route={{ page: 'dev', brandId: null, category: null }} navigate={() => {}} />);
  expect(await screen.findByText(/for the archive’s owner/)).toBeInTheDocument();
});
