import React, { useState } from 'react';
import { FashionArchiveAPI } from '../services/api';
import { AuthShell, Button, Field, LinkButton, Notice } from './AuthShell';

/**
 * The whole signed-out experience: sign in, create an account, confirm your
 * email, and reset a forgotten password.
 *
 * One component with a `mode` rather than five routed pages, because these
 * screens hand off to each other constantly — a failed login offers a reset, a
 * registration lands on "check your email", a reset returns to sign-in. Routing
 * would mean five components all reaching for the same email address.
 *
 * Server error *codes* drive the branching, never the prose. The messages are
 * meant to be readable by a person and changeable without breaking this file.
 */
export default function AuthPanel({ onAuthenticated, initialMode, initialNotice, resetToken }) {
  const [mode, setMode] = useState(initialMode || 'login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState(initialNotice || '');

  const go = (next) => {
    setMode(next);
    setError('');
    setNotice('');
    setPassword('');
  };

  /** Runs an auth call with the shared busy/error handling. */
  const attempt = async (fn) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      return await fn();
    } catch (err) {
      console.error('Auth error:', err);
      setError('Could not reach the server. Please try again.');
      return null;
    } finally {
      setBusy(false);
    }
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    const result = await attempt(() => FashionArchiveAPI.login(email.trim(), password));
    if (!result) return;

    if (result.ok) {
      onAuthenticated(result.user);
      return;
    }
    // An unverified account is a recoverable state, not a dead end: offer the
    // one action that fixes it rather than just reporting the refusal.
    if (result.code === 'EMAIL_NOT_VERIFIED') {
      setMode('check-email');
      setNotice('Your email address has not been confirmed yet.');
      return;
    }
    setError(result.error || 'Sign in failed.');
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    const result = await attempt(() =>
      FashionArchiveAPI.register(email.trim(), password, displayName.trim())
    );
    if (!result) return;

    if (result.ok) {
      // Deliberately the same screen whether or not the address already had an
      // account — the server does not say, so neither can this.
      setMode('check-email');
      setNotice('');
      return;
    }
    setError(result.error || 'Could not create the account.');
  };

  const handleResend = async () => {
    const result = await attempt(() => FashionArchiveAPI.resendVerification(email.trim()));
    if (result) setNotice('If that account still needs confirming, a new link is on its way.');
  };

  const handleForgot = async (e) => {
    e.preventDefault();
    const result = await attempt(() => FashionArchiveAPI.requestPasswordReset(email.trim()));
    if (result) setNotice('If that account exists, a reset link is on its way.');
  };

  const handleReset = async (e) => {
    e.preventDefault();
    const result = await attempt(() => FashionArchiveAPI.resetPassword(resetToken, password));
    if (!result) return;

    if (result.ok) {
      go('login');
      setNotice('Password updated. Please sign in.');
      return;
    }
    setError(result.error || 'That reset link is invalid or has expired.');
  };

  if (mode === 'check-email') {
    return (
      <AuthShell
        title="Confirm your email"
        subtitle={`We sent a confirmation link to ${email || 'your address'}. Open it to finish setting up your archive.`}
      >
        <Notice kind="info">{notice}</Notice>
        <Notice>{error}</Notice>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Button type="button" onClick={handleResend} disabled={busy || !email}>
            {busy ? 'Please wait…' : 'Send it again'}
          </Button>
          <div>
            <LinkButton onClick={() => go('login')} disabled={busy}>
              Back to sign in
            </LinkButton>
          </div>
        </div>
        <p style={hint}>The link expires in 24 hours.</p>
      </AuthShell>
    );
  }

  if (mode === 'reset') {
    return (
      <AuthShell title="New password" subtitle="Enter a new password for your account.">
        <form onSubmit={handleReset}>
          <Field
            label="New password" type="password" value={password}
            onChange={setPassword} autoFocus disabled={busy}
            placeholder="At least 8 characters"
          />
          <Notice>{error}</Notice>
          <Button type="submit" disabled={busy || password.length < 8}>
            {busy ? 'Please wait…' : 'Update password'}
          </Button>
        </form>
        <p style={hint}>This will sign you out everywhere else.</p>
      </AuthShell>
    );
  }

  if (mode === 'forgot') {
    return (
      <AuthShell title="Reset password" subtitle="We'll email you a link to choose a new one.">
        <form onSubmit={handleForgot}>
          <Field
            label="Email" type="email" value={email}
            onChange={setEmail} autoFocus disabled={busy}
            placeholder="you@example.com"
          />
          <Notice kind="info">{notice}</Notice>
          <Notice>{error}</Notice>
          <Button type="submit" disabled={busy || !email.trim()}>
            {busy ? 'Please wait…' : 'Send reset link'}
          </Button>
        </form>
        <div style={{ marginTop: 20 }}>
          <LinkButton onClick={() => go('login')} disabled={busy}>Back to sign in</LinkButton>
        </div>
      </AuthShell>
    );
  }

  if (mode === 'register') {
    return (
      <AuthShell title="Create account" subtitle="Your archive, your favourites, your brands.">
        <form onSubmit={handleRegister}>
          <Field label="Name" value={displayName} onChange={setDisplayName}
                 autoFocus disabled={busy} maxLength={60} placeholder="What should we call you?" />
          <Field label="Email" type="email" value={email} onChange={setEmail}
                 disabled={busy} placeholder="you@example.com" />
          <Field label="Password" type="password" value={password} onChange={setPassword}
                 disabled={busy} placeholder="At least 8 characters" />
          <Notice>{error}</Notice>
          <Button type="submit" disabled={busy || !email.trim() || password.length < 8}>
            {busy ? 'Please wait…' : 'Create account'}
          </Button>
        </form>
        <div style={{ marginTop: 20 }}>
          <LinkButton onClick={() => go('login')} disabled={busy}>
            Already have an account? Sign in
          </LinkButton>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Sign in" subtitle="Enter your details to reach your archive.">
      <form onSubmit={handleLogin}>
        <Field label="Email" type="email" value={email} onChange={setEmail}
               autoFocus disabled={busy} placeholder="you@example.com" />
        <Field label="Password" type="password" value={password} onChange={setPassword}
               disabled={busy} />
        <Notice kind="info">{notice}</Notice>
        <Notice>{error}</Notice>
        <Button type="submit" disabled={busy || !email.trim() || !password}>
          {busy ? 'Please wait…' : 'Sign in'}
        </Button>
      </form>
      <div style={{ marginTop: 20, display: 'flex', justifyContent: 'space-between' }}>
        <LinkButton onClick={() => go('register')} disabled={busy}>Create an account</LinkButton>
        <LinkButton onClick={() => go('forgot')} disabled={busy}>Forgot password?</LinkButton>
      </div>
    </AuthShell>
  );
}

const hint = {
  marginTop: 20,
  fontSize: 10,
  color: '#cccccc',
  lineHeight: 1.5,
  letterSpacing: '0.05em',
};
