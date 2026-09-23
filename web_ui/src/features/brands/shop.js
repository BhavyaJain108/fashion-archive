// Small helpers the shop front and the product page share.

const SYMBOL = { USD: '$', EUR: '€', GBP: '£', CAD: 'CA$', AUD: 'A$', JPY: '¥', CNY: '¥', KRW: '₩' };

export function formatPrice(value, currency = 'USD') {
  if (value === null || value === undefined) return '';
  const n = Number(value);
  if (!Number.isFinite(n)) return '';
  const sym = SYMBOL[currency] || `${currency} `;
  const whole = Number.isInteger(n) ? n.toLocaleString('en-US') : n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${sym}${whole}`;
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
