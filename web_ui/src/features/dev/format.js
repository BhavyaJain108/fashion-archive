// Numbers and times as the machine room writes them. Plain, tabular, no units
// invented: a blank is "—", never a zero pretending to be a measurement.

const MINUTE = 60 * 1000;

export function ago(iso) {
  if (!iso) return '—';
  const mins = (Date.now() - new Date(iso).getTime()) / MINUTE;
  if (Number.isNaN(mins)) return '—';
  if (mins < 1) return 'just now';
  if (mins < 60) return `${Math.round(mins)}m ago`;
  if (mins < 1440) return `${(mins / 60).toFixed(1)}h ago`;
  return `${(mins / 1440).toFixed(1)}d ago`;
}

export function due(iso) {
  if (!iso) return '—';
  const mins = (new Date(iso).getTime() - Date.now()) / MINUTE;
  if (Number.isNaN(mins)) return '—';
  if (mins <= 0) return 'due now';
  if (mins < 60) return `in ${Math.round(mins)}m`;
  if (mins < 1440) return `in ${(mins / 60).toFixed(1)}h`;
  return `in ${(mins / 1440).toFixed(1)}d`;
}

export const n = (v) => (v == null ? '—' : Number(v).toLocaleString());

export const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`);

export const usd = (v, digits = 2) => (v == null ? '—' : `$${Number(v).toFixed(digits)}`);

export const secs = (v) => (v == null ? '—' : `${Number(v).toFixed(1)}s`);

export function gb(bytes) {
  if (bytes == null) return '—';
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

export function hours(seconds) {
  if (seconds == null) return '—';
  const h = seconds / 3600;
  return h >= 24 ? `${(h / 24).toFixed(0)}d` : `${h.toFixed(0)}h`;
}

export function dateShort(iso) {
  return iso ? iso.slice(0, 10) : '—';
}
