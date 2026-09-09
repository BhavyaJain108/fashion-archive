import React from 'react';

/**
 * Shared frame for every auth screen.
 *
 * Kept separate so the five forms only describe their own fields; spacing,
 * heading and error presentation are decided once here and cannot drift apart
 * between screens.
 */
export function AuthShell({ title, subtitle, children }) {
  return (
    <div style={styles.overlay}>
      <div style={styles.dialog}>
        <h3 style={styles.title}>{title}</h3>
        {subtitle && <p style={styles.subtitle}>{subtitle}</p>}
        {children}
      </div>
    </div>
  );
}

export function Field({ label, type = 'text', value, onChange, autoFocus, disabled, ...rest }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label style={styles.label}>{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoFocus={autoFocus}
        disabled={disabled}
        className="mac-input"
        style={styles.input}
        {...rest}
      />
    </div>
  );
}

/** Errors and confirmations share one component so they cannot look different. */
export function Notice({ kind = 'error', children }) {
  if (!children) return null;
  const palette = kind === 'error'
    ? { background: '#ffe6e6', border: '1px solid #ff9999', color: '#cc0000' }
    : { background: '#e8f5e9', border: '1px solid #a5d6a7', color: '#1b5e20' };
  return <div style={{ ...styles.notice, ...palette }}>{children}</div>;
}

export function Button({ children, ...rest }) {
  return (
    <button className="mac-button" style={{ width: '100%' }} {...rest}>
      {children}
    </button>
  );
}

/** A button that reads as a link, for moving between auth screens. */
export function LinkButton({ children, onClick, disabled }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} style={styles.link}>
      {children}
    </button>
  );
}

const styles = {
  overlay: {
    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.5)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 2000,
  },
  dialog: {
    backgroundColor: 'var(--mac-bg)',
    border: '2px outset var(--mac-bg)',
    padding: 16, minWidth: 400, maxWidth: 460,
  },
  title: { margin: '0 0 8px 0', textAlign: 'center', fontSize: 16, fontWeight: 'bold' },
  subtitle: { margin: '0 0 16px 0', textAlign: 'center', fontSize: 12, lineHeight: 1.4 },
  label: { display: 'block', marginBottom: 4, fontSize: 12, fontWeight: 'bold' },
  input: { width: '100%', padding: '4px 6px', fontSize: 12 },
  notice: { marginBottom: 12, padding: 6, fontSize: 11, textAlign: 'center', lineHeight: 1.4 },
  link: {
    background: 'none', border: 'none', padding: 0,
    fontSize: 11, textDecoration: 'underline', cursor: 'pointer', color: '#333',
  },
};
