import React from 'react';

/**
 * Shared frame for every auth screen.
 *
 * Matches the archive's own visual language rather than inventing one: the
 * JetBrains Mono stack, 10px uppercase labels at 0.15em tracking, hairline
 * #e0e0e0 borders, black on white with #666 body and #999 secondary. Those
 * values come from HighFashionV2.css and TopBar.css, so the sign-in screen
 * reads as part of the same application as the page behind it.
 *
 * Kept separate from the forms so spacing, type and error presentation are
 * decided once and cannot drift between the five screens.
 */

const MONO = "'JetBrains Mono', 'SF Mono', 'Monaco', monospace";

export function AuthShell({ title, subtitle, children }) {
  return (
    <div style={styles.overlay}>
      <div style={styles.panel}>
        <div style={styles.header}>{title}</div>
        <div style={styles.body}>
          {subtitle && <p style={styles.subtitle}>{subtitle}</p>}
          {children}
        </div>
      </div>
    </div>
  );
}

export function Field({ label, type = 'text', value, onChange, autoFocus, disabled, ...rest }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={styles.label}>{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoFocus={autoFocus}
        disabled={disabled}
        style={styles.input}
        onFocus={(e) => { e.target.style.borderBottomColor = '#000000'; }}
        onBlur={(e) => { e.target.style.borderBottomColor = '#e0e0e0'; }}
        {...rest}
      />
    </div>
  );
}

/** Errors and confirmations share one component so they cannot diverge. */
export function Notice({ kind = 'error', children }) {
  if (!children) return null;
  return (
    <div style={{ ...styles.notice, color: kind === 'error' ? '#000000' : '#666666' }}>
      <span style={{ ...styles.noticeMark, background: kind === 'error' ? '#000000' : '#cccccc' }} />
      {children}
    </div>
  );
}

export function Button({ children, disabled, ...rest }) {
  return (
    <button
      disabled={disabled}
      style={{ ...styles.button, ...(disabled ? styles.buttonDisabled : null) }}
      onMouseEnter={(e) => { if (!disabled) e.target.style.background = '#333333'; }}
      onMouseLeave={(e) => { if (!disabled) e.target.style.background = '#000000'; }}
      {...rest}
    >
      {children}
    </button>
  );
}

/** A text button for moving between auth screens. */
export function LinkButton({ children, onClick, disabled }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={styles.link}
      onMouseEnter={(e) => { if (!disabled) e.target.style.color = '#000000'; }}
      onMouseLeave={(e) => { if (!disabled) e.target.style.color = '#999999'; }}
    >
      {children}
    </button>
  );
}

const styles = {
  overlay: {
    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
    background: '#ffffff',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 2000,
    fontFamily: MONO,
  },
  panel: {
    width: 380,
    maxWidth: 'calc(100vw - 48px)',
    border: '1px solid #e0e0e0',
    background: '#ffffff',
  },
  header: {
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: '0.15em',
    color: '#999999',
    background: '#fafafa',
    borderBottom: '1px solid #e0e0e0',
    padding: '10px 20px',
  },
  body: { padding: 24 },
  subtitle: {
    margin: '0 0 24px 0',
    fontSize: 12,
    lineHeight: 1.6,
    color: '#666666',
  },
  label: {
    display: 'block',
    marginBottom: 6,
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: '0.15em',
    color: '#999999',
  },
  input: {
    width: '100%',
    boxSizing: 'border-box',
    fontFamily: MONO,
    fontSize: 12,
    color: '#000000',
    background: 'transparent',
    border: 'none',
    borderBottom: '1px solid #e0e0e0',
    borderRadius: 0,
    padding: '6px 0',
    outline: 'none',
    transition: 'border-color 0.15s',
  },
  button: {
    width: '100%',
    fontFamily: MONO,
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    color: '#ffffff',
    background: '#000000',
    border: 'none',
    borderRadius: 0,
    padding: '12px 16px',
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  buttonDisabled: {
    background: '#e0e0e0',
    color: '#999999',
    cursor: 'default',
  },
  notice: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 8,
    margin: '0 0 16px 0',
    fontSize: 11,
    lineHeight: 1.5,
  },
  noticeMark: {
    display: 'block',
    width: 2,
    minWidth: 2,
    alignSelf: 'stretch',
  },
  link: {
    fontFamily: MONO,
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    color: '#999999',
    background: 'none',
    border: 'none',
    padding: 0,
    cursor: 'pointer',
    transition: 'color 0.15s',
  },
};
