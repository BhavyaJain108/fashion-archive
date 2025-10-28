import React, { useState } from 'react';
import '../styles/global.css';

function LoginModal({ isOpen, onLogin, onClose }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [showRegisterOption, setShowRegisterOption] = useState(false);
  const [isRegistering, setIsRegistering] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!username.trim() || !password.trim()) {
      setError('Please enter both username and password');
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      const response = await fetch('http://localhost:8081/api/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username: username.trim(),
          password: password,
          action: isRegistering ? 'register' : 'login'
        }),
      });

      const data = await response.json();

      if (data.success) {
        // Store session token in localStorage
        localStorage.setItem('fashionArchiveToken', data.session_token);
        localStorage.setItem('fashionArchiveUser', JSON.stringify(data.user));
        
        // Call parent component's login handler
        onLogin(data.user, data.session_token);
        
        // Clear form
        setUsername('');
        setPassword('');
        setShowRegisterOption(false);
        setIsRegistering(false);
        
      } else {
        // Check if we should show registration option
        if (data.can_register) {
          setShowRegisterOption(true);
          setError(`User '${username}' not found.`);
        } else {
          setError(data.error || 'Login failed');
        }
      }
    } catch (error) {
      setError('Connection failed. Please check if the server is running.');
      console.error('Login error:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateAccount = () => {
    setIsRegistering(true);
    setShowRegisterOption(false);
    setError('');
  };

  const handleBackToLogin = () => {
    setIsRegistering(false);
    setShowRegisterOption(false);
    setError('');
  };

  console.log('🔍 LoginModal render - isOpen:', isOpen);
  
  if (!isOpen) {
    console.log('🔍 LoginModal not open, returning null');
    return null;
  }
  
  console.log('🔍 LoginModal rendering modal');

  return (
    <div className="mac-modal-overlay" style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 2000
      }}>
      <div className="mac-dialog" style={{
        backgroundColor: 'var(--mac-bg)',
        border: '2px outset var(--mac-bg)',
        padding: '16px',
        minWidth: '400px',
        maxWidth: '500px'
      }}>
        <h3 style={{ 
          margin: '0 0 16px 0', 
          textAlign: 'center',
          fontSize: '16px',
          fontWeight: 'bold'
        }}>
          {isRegistering ? 'Create Account' : 'Fashion Archive Login'}
        </h3>
        <div style={{ marginBottom: '16px' }}>
          {isRegistering ? (
            <p style={{ margin: 0, textAlign: 'center', fontSize: '12px' }}>
              Create your personal fashion archive account:
            </p>
          ) : (
            <p style={{ margin: 0, textAlign: 'center', fontSize: '12px' }}>
              Enter your name and password to access your archive:
            </p>
          )}
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '12px' }}>
            <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: 'bold' }}>
              Name:
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter your name"
              maxLength={35}
              disabled={isLoading}
              autoFocus
              className="mac-input"
              style={{ width: '100%', padding: '4px 6px', fontSize: '12px' }}
            />
          </div>

          <div style={{ marginBottom: '12px' }}>
            <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: 'bold' }}>
              Password:
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              disabled={isLoading}
              className="mac-input"
              style={{ width: '100%', padding: '4px 6px', fontSize: '12px' }}
            />
          </div>

          {error && (
            <div style={{ 
              marginBottom: '12px',
              padding: '6px',
              backgroundColor: '#ffe6e6',
              border: '1px solid #ff9999',
              fontSize: '11px',
              textAlign: 'center',
              color: '#cc0000'
            }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <button 
              type="submit" 
              disabled={isLoading || !username.trim() || !password.trim()}
              className="mac-button"
              style={{ width: '100%' }}
            >
              {isLoading ? 'Please wait...' : (isRegistering ? 'Create Account' : 'Login')}
            </button>

            {showRegisterOption && !isRegistering && (
              <button 
                type="button"
                onClick={handleCreateAccount}
                className="mac-button"
                disabled={isLoading}
                style={{ width: '100%' }}
              >
                Create New Account
              </button>
            )}

            {isRegistering && (
              <button 
                type="button"
                onClick={handleBackToLogin}
                className="mac-button"
                disabled={isLoading}
                style={{ width: '100%' }}
              >
                Back to Login
              </button>
            )}
          </div>
        </form>

        <div style={{ 
          marginTop: '16px',
          textAlign: 'center',
          fontSize: '10px',
          color: '#666',
          lineHeight: 1.3
        }}>
          {isRegistering ? (
            "Your account will be created with a personal data space."
          ) : (
            "New here? Enter any name and password, then click 'Create New Account' if prompted."
          )}
        </div>
      </div>
    </div>
  );
}

export default LoginModal;