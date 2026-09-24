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
  try {
    return new Intl.NumberFormat('en', {
      style: 'currency', currency: currency || 'USD', minimumFractionDigits: 0, maximumFractionDigits: n >= 100 ? 0 : 2,
    }).format(n);
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

export function useMoney() {
  const [currency, setCurrencyState] = useState(() => remembered() || guessCurrency());
  const [rates, setRates] = useState(null);

  useEffect(() => {
    let alive = true;
    fetch(`${ApiClient.BASE_URL}/api/archive/rates`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => { if (alive && body && body.ok) setRates(body.rates); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const setCurrency = useCallback((c) => {
    setCurrencyState(c);
    try { window.localStorage.setItem(KEY, c); } catch { /* fine */ }
  }, []);

  const format = useCallback((amount, shopCurrency) => priceText(amount, shopCurrency, currency, rates), [currency, rates]);
  const exact = useCallback((amount, shopCurrency) => formatMoney(amount, shopCurrency || currency), [currency]);

  return { currency, setCurrency, rates, format, exact };
}
