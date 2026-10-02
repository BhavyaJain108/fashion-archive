import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import DevApi from './DevApi';
import DevEndpoints from '../../shared/api/dev';

jest.mock('../../shared/api/dev', () => ({
  __esModule: true,
  default: { getDocs: jest.fn(), call: jest.fn() },
}));

const DOCS = {
  generated_at: '2026-10-02T10:00:00Z',
  totals: { operations: 1, legacy: 1, undocumented: 0 },
  mcp: { endpoint: '/mcp', protocol: '2025-06-18', tools: 1, auth: 'session cookie' },
  families: [
    {
      key: 'catalogue',
      name: 'Catalogue',
      about: 'What the shop shows.',
      operations: [
        {
          name: 'catalogue_products',
          method: 'GET',
          path: '/api/catalogue/products',
          summary: 'The products the shop shows.',
          detail: '',
          params: [
            { name: 'fields', type: 'string', required: false, choices: ['tiles', 'records'], default: 'tiles', doc: 'Shape.' },
            { name: 'brand', type: 'string', required: false, doc: 'One brand.' },
            { name: 'sale', type: 'boolean', required: false, default: false, doc: 'Reduced only.' },
            { name: 'limit', type: 'integer', required: false, default: 60, doc: 'How many.' },
          ],
          reads: ['products'],
          writes: false,
          owner: false,
          replaces: ['archive_storefront'],
          example: { limit: 12 },
          mcp_tool: 'catalogue_products',
        },
      ],
      legacy: [
        { method: 'GET', path: '/api/archive/storefront', endpoint: 'archive_storefront', summary: 'The old grid.', detail: '', public: false, replaced_by: 'catalogue_products' },
      ],
    },
  ],
};

beforeEach(() => {
  window.sessionStorage.clear();
  DevEndpoints.getDocs.mockResolvedValue(DOCS);
  DevEndpoints.call.mockResolvedValue({ status: 200, ms: 12, body: { products: [], total: 0 }, url: '/api/catalogue/products?limit=12' });
});

test('an operation shows its route, its MCP tool and its parameters', async () => {
  render(<DevApi />);
  expect(await screen.findByText('/api/catalogue/products')).toBeInTheDocument();
  expect(screen.getByText('catalogue_products')).toBeInTheDocument();
  expect(screen.getByText('tiles | records = "tiles"')).toBeInTheDocument();
  expect(screen.getByText('How many.')).toBeInTheDocument();
});

test('try it builds a form from the parameters and shows the answer', async () => {
  render(<DevApi />);
  fireEvent.click(await screen.findByText('▸ try it'));
  const limit = screen.getByLabelText(/^limit/);
  expect(limit.value).toBe('12'); // the example fills the form
  fireEvent.change(screen.getByLabelText(/^brand/), { target: { value: 'acne.com' } });
  fireEvent.click(screen.getByText('call'));
  await waitFor(() => expect(DevEndpoints.call).toHaveBeenCalled());
  expect(DevEndpoints.call).toHaveBeenCalledWith('GET', '/api/catalogue/products', { fields: 'tiles', brand: 'acne.com', limit: 12 });
  expect(await screen.findByText('200')).toBeInTheDocument();
  expect(screen.getByText(/"total": 0/)).toBeInTheDocument();
});

test('legacy routes fold away and point at their replacement', async () => {
  render(<DevApi />);
  fireEvent.click(await screen.findByText('▸ 1 legacy route'));
  expect(screen.getByText('/api/archive/storefront')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'catalogue_products' })).toHaveAttribute('href', '#op-catalogue_products');
});
