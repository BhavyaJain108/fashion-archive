import React, { useEffect, useState } from 'react';
import { FashionArchiveAPI } from '../../shared/api';
import { AuthShell, Button, Notice } from './AuthShell';

// What the API's `?auth_error=` codes mean to a reader. Anything unlisted gets
// the generic line — a code we did not anticipate should still say something
// true rather than render blank.
const MESSAGES = {
  CANCELLED: 'Sign-in was cancelled.',
  EMAIL_NOT_VERIFIED:
    'That account has no confirmed email address, so we cannot sign you in with it.',
  ACCOUNT_DISABLED: 'That account is closed.',
  PROVIDER_UNAVAILABLE: 'That sign-in method is not available right now.',
  INVALID_STATE: 'That sign-in took too long. Please try again.',
};

const LABELS = { google: 'Continue with Google', apple: 'Continue with Apple' };
const NAMES = { google: 'Google', apple: 'Apple' };

// Name only what is actually on offer: promising Apple when Apple is not
// configured reads as a button that failed to load.
function subtitle(providers) {
  const names = providers.map((p) => NAMES[p] || p);
  const list = names.length > 1
    ? `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`
    : names[0];
  return `Use your ${list} account to reach your archive.`;
}

/**
 * The signed-out screen: one button per configured provider.
 *
 * There is no form. Google and Apple have already verified the address, which
 * is what removed the password, the confirmation email and the reset flow —
 * and with them every screen that used to exist here.
 *
 * Which buttons appear comes from the API rather than being hardcoded, so a
 * provider whose credentials are not set is invisible instead of offering a
 * button that dead-ends.
 */
export default function AuthPanel({ initialNotice }) {
  const [providers, setProviders] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    FashionArchiveAPI.getProviders()
      .then((list) => alive && setProviders(list))
      .catch(() => {
        if (!alive) return;
        setProviders([]);
        setError('Could not reach the server. Please try again.');
      });
    return () => { alive = false; };
  }, []);

  // A full navigation, not fetch: the provider needs to show its own page, and
  // it will send the browser back to the API's callback afterwards.
  const signIn = (provider) => {
    window.location.href = FashionArchiveAPI.oauthStartUrl(provider);
  };

  if (providers === null) {
    return (
      <AuthShell title="Sign in">
        <Notice kind="info">Loading…</Notice>
      </AuthShell>
    );
  }

  if (providers.length === 0) {
    return (
      <AuthShell title="Sign in">
        <Notice>{error || 'No sign-in method is configured.'}</Notice>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Sign in" subtitle={subtitle(providers)}>
      <Notice kind="info">{initialNotice}</Notice>
      <Notice>{error}</Notice>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {providers.map((provider) => (
          <Button key={provider} type="button" onClick={() => signIn(provider)}>
            {LABELS[provider] || `Continue with ${provider}`}
          </Button>
        ))}
      </div>
      <p style={hint}>
        We only ask for your name and email address, and we never see your password.
      </p>
    </AuthShell>
  );
}

/** Turns an `?auth_error=` code from the callback into something readable. */
export function authErrorMessage(code) {
  return MESSAGES[code] || 'Sign-in did not complete. Please try again.';
}

const hint = {
  marginTop: 20,
  fontSize: 10,
  color: '#cccccc',
  lineHeight: 1.5,
  letterSpacing: '0.05em',
};
