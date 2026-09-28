import React from 'react';

import { ago } from './format';

// A new brand's first minutes, as six steps: probe → signature → wall → plan →
// first read → verdict. The worker writes each step to the dossier as it happens
// and this draws them — the running one with the sheen, the done ones with what
// they found, the skipped ones saying why. It is the same shape as the run's
// progress bar, one level up: not "how far through the pages" but "how far
// through understanding the shop".
const WORDS = {
  probe: 'probing',
  signature: 'signing',
  wall: 'classifying the wall',
  plan: 'planning',
  'first-read': 'first read',
  verdict: 'verdict',
};

export default function Onboarding({ onboarding, compact = false }) {
  if (!onboarding || !onboarding.steps) return null;
  const running = onboarding.steps.find((s) => s.status === 'running');
  const finished = !!onboarding.finished_at;
  return (
    <div className={`dev-onboard${compact ? ' compact' : ''}`} role="status" aria-live="polite">
      <div className="dev-onboard-head">
        <span className="dev-live-k">
          {finished ? 'onboarded' : running ? `onboarding · ${WORDS[running.name] || running.name}` : 'onboarding'}
        </span>
        <span className="dev-muted">
          {' '}· started {ago(onboarding.started_at)}
          {finished ? ` · finished ${ago(onboarding.finished_at)}` : ''}
        </span>
      </div>
      <ol className="dev-steps">
        {onboarding.steps.map((s) => (
          <li key={s.name} className={`dev-step ${s.status}`}>
            <span className="dev-step-dot" aria-hidden="true" />
            <span className="dev-step-name">{WORDS[s.name] || s.name}</span>
            {!compact && s.text && <span className="dev-step-text">{s.text}</span>}
            {compact && s.status === 'done' && s.text && <span className="dev-step-text">{s.text.slice(0, 60)}</span>}
          </li>
        ))}
      </ol>
      {running && <div className="dev-live-track indeterminate"><div className="dev-live-fill" /></div>}
    </div>
  );
}
