// Small helpers the shop front and the product page share.

import { showPrice, shopPrice } from '../../shared/money';

// A price reads in the visitor's currency, converted with the day's rates and
// marked approximate; the shop's own figure is what the card is charged.
export function formatPrice(value, currency = 'USD') {
  if (value === null || value === undefined) return '';
  return showPrice(value, currency);
}

export function shopFigure(value, currency = 'USD') {
  if (value === null || value === undefined) return '';
  return shopPrice(value, currency);
}

export const count = (n) => Number(n || 0).toLocaleString('en-US');

// The shop's CDN is the live copy and can stop resolving; the archive kept bytes
// for some products, so a dead image falls back to ours before it goes blank.
export function fallbackOnError(archived = []) {
  return (e) => {
    const img = e.currentTarget;
    const next = (archived || []).find((u) => u !== img.getAttribute('src'));
    if (next) img.src = next;
    else img.style.visibility = 'hidden';
  };
}
