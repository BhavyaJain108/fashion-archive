import { useCallback, useEffect, useState } from 'react';

import ApiClient from './api/client';

// Prices in the visitor's own currency. The shops price in theirs; the archive
// converts for display with the day's rates and always keeps the shop's figure
// within reach, because the shop's figure is what the card will be charged.

// Where a browser's region usually pays. Anything else falls back to the dollar.
const REGION_CURRENCY = {
  US: 'USD', CA: 'CAD', GB: 'GBP', IE: 'EUR', AU: 'AUD', NZ: 'NZD', IN: 'INR', JP: 'JPY',
  KR: 'KRW', CN: 'CNY', HK: 'HKD', SG: 'SGD', CH: 'CHF', SE: 'SEK', NO: 'NOK', DK: 'DKK',
  PL: 'PLN', CZ: 'CZK', HU: 'HUF', RU: 'RUB', TR: 'TRY', BR: 'BRL', MX: 'MXN', ZA: 'ZAR',
  AE: 'AED', IL: 'ILS', TH: 'THB', ID: 'IDR', PH: 'PHP', MY: 'MYR',
  DE: 'EUR', FR: 'EUR', IT: 'EUR', ES: 'EUR', NL: 'EUR', BE: 'EUR', AT: 'EUR', PT: 'EUR',
  FI: 'EUR', GR: 'EUR', LT: 'EUR', LV: 'EUR', EE: 'EUR', SK: 'EUR', SI: 'EUR', HR: 'EUR',
};

export const CURRENCIES = ['USD', 'EUR', 'GBP', 'INR', 'AUD', 'CAD', 'JPY', 'CHF', 'SGD', 'AED'];

const KEY = 'money:currency';

export function guessCurrency(locale) {
  const tag = locale || (typeof navigator !== 'undefined' && navigator.language) || 'en-US';
  const region = (tag.split(/[-_]/)[1] || '').toUpperCase();
  return REGION_CURRENCY[region] || 'USD';
}

function remembered() {
  try {
    return window.localStorage.getItem(KEY) || null;
  } catch {
    return null;
  }
}

export function convert(amount, from, to, rates) {
  const n = typeof amount === 'string' ? parseFloat(amount.replace(/[^\d.]/g, '')) : Number(amount);
  if (!Number.isFinite(n)) return null;
  if (!from || from === to) return n;
  if (!rates || !rates[from] || !rates[to]) return null;
  // Rates are against the dollar: shop currency → USD → the visitor's.
  return (n / rates[from]) * rates[to];
}

export function formatMoney(amount, currency) {
  if (amount === null || amount === undefined || amount === '') return '';
  const n = typeof amount === 'string' ? parseFloat(amount.replace(/[^\d.]/g, '')) : Number(amount);
  if (!Number.isFinite(n)) return String(amount);
  // Whole amounts read whole; anything else keeps its cents. Converted figures are
  // rounded first so a rate never produces a third decimal.
  const r = Math.round(n * 100) / 100;
  const digits = Number.isInteger(r) ? 0 : 2;
  try {
    return new Intl.NumberFormat('en', {
      style: 'currency', currency: currency || 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits,
    }).format(r);
  } catch {
    return `${currency ? `${currency} ` : ''}${n.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  }
}

// What a price reads as on the page: converted when the rate is known, marked as
// approximate; the shop's own figure when it is not, or when the currencies match.
export function priceText(amount, shopCurrency, currency, rates) {
  if (amount === null || amount === undefined || amount === '') return '';
  if (!shopCurrency || shopCurrency === currency) return formatMoney(amount, shopCurrency || currency);
  const converted = convert(amount, shopCurrency, currency, rates);
  if (converted === null) return formatMoney(amount, shopCurrency);
  return `≈ ${formatMoney(converted, currency)}`;
}

// One store for the whole shop: the chosen currency and the day's rates. A
// formatter anywhere reads it, so no page has to pass money down through props.
const store = {
  currency: remembered() || guessCurrency(),
  rates: null,
  fetched: false,
  listeners: new Set(),
};

function notify() {
  store.listeners.forEach((fn) => fn());
}

export function setCurrency(c) {
  store.currency = c;
  try { window.localStorage.setItem(KEY, c); } catch { /* fine */ }
  notify();
}

export function loadRates() {
  if (store.fetched) return;
  store.fetched = true;
  fetch(`${ApiClient.BASE_URL}/api/archive/rates`, { credentials: 'include' })
    .then((r) => (r.ok ? r.json() : null))
    .then((body) => { if (body && body.ok) { store.rates = body.rates; notify(); } })
    .catch(() => { store.fetched = false; });
}

// The price as the page shows it, in the visitor's currency when the rate is known.
export function showPrice(amount, shopCurrency) {
  return priceText(amount, shopCurrency, store.currency, store.rates);
}

// The shop's own figure, which is what the card is charged.
export function shopPrice(amount, shopCurrency) {
  return formatMoney(amount, shopCurrency || store.currency);
}

export function currentCurrency() {
  return store.currency;
}

export function useMoney() {
  const [, tick] = useState(0);
  useEffect(() => {
    const fn = () => tick((n) => n + 1);
    store.listeners.add(fn);
    loadRates();
    return () => { store.listeners.delete(fn); };
  }, []);
  const set = useCallback((c) => setCurrency(c), []);
  return { currency: store.currency, setCurrency: set, rates: store.rates, format: showPrice, exact: shopPrice };
}
