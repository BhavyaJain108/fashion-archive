import React from 'react';

/**
 * Reusable Mac-style modal component
 * 
 * @param {Object} props
 * @param {boolean} props.show - Whether to show the modal
 * @param {function} props.onClose - Function to call when modal is closed
 * @param {string} props.type - Modal type: 'success', 'error', 'warning', 'info', 'confirm'
 * @param {string} props.title - Modal title
 * @param {string} props.message - Modal message content
 * @param {string} props.confirmText - Text for confirm button (default: 'OK')
 * @param {string} props.cancelText - Text for cancel button (only shown for confirm type)
 * @param {function} props.onConfirm - Function to call when confirm button is clicked
 * @param {number} props.width - Modal width in pixels (default: 400)
 * @param {number} props.zIndex - Modal z-index (default: 2000)
 */
function MacModal({
  show = false,
  onClose,
  type = 'info',
  title = '',
  message = '',
  confirmText = 'OK',
  cancelText = 'Cancel',
  onConfirm = null,
  width = 400,
  zIndex = 2000
}) {
  if (!show) return null;

  const getIcon = () => {
    switch (type) {
      case 'success': return '✅';
      case 'error': return '❌';
      case 'warning': return '⚠️';
      case 'confirm': return '❓';
      case 'info':
      default: return 'ℹ️';
    }
  };

  const getButtonColor = () => {
    switch (type) {
      case 'success': return '#007bff';
      case 'error': return '#dc3545';
      case 'warning': return '#ffc107';
      case 'confirm': return '#007bff';
      case 'info':
      default: return '#6c757d';
    }
  };

  const getMessageBgColor = () => {
    switch (type) {
      case 'success': return '#f0fff0';
      case 'error': return '#fff0f0';
      case 'warning': return '#fff8f0';
      case 'confirm': return '#f0f8ff';
      case 'info':
      default: return '#f8f9fa';
    }
  };

  const handleConfirm = () => {
    if (onConfirm) {
      onConfirm();
    } else {
      onClose();
    }
  };

  const isConfirmType = type === 'confirm';

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
      zIndex: zIndex
    }}>
      <div className="mac-dialog" style={{
        backgroundColor: 'var(--mac-bg)',
        border: '2px outset var(--mac-bg)',
        padding: '20px',
        width: `${width}px`,
        minHeight: isConfirmType ? '160px' : '180px',
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
        textAlign: 'center'
      }}>
        
        {/* Icon and Title */}
        <div style={{ marginBottom: '16px' }}>
          <div style={{ 
            fontSize: '48px', 
            marginBottom: '12px',
            lineHeight: 1
          }}>
            {getIcon()}
          </div>
          {title && (
            <div className="mac-label title" style={{ 
              fontSize: '14px',
              fontWeight: 'bold'
            }}>
              {title}
            </div>
          )}
        </div>
        
        {/* Message */}
        {message && (
          <div style={{ 
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <div className="mac-text" style={{ 
              fontSize: '12px',
              lineHeight: '1.4',
              color: '#333',
              padding: '12px',
              border: '1px inset var(--mac-bg)',
              backgroundColor: getMessageBgColor(),
              borderRadius: '2px'
            }}>
              {message}
            </div>
          </div>
        )}
        
        {/* Buttons */}
        <div style={{ 
          marginTop: '16px',
          display: 'flex',
          justifyContent: 'center',
          gap: isConfirmType ? '12px' : '0'
        }}>
          {isConfirmType && (
            <button 
              className="mac-button"
              onClick={onClose}
              style={{ 
                minWidth: '80px'
              }}
            >
              {cancelText}
            </button>
          )}
          <button 
            className="mac-button"
            onClick={handleConfirm}
            style={{ 
              minWidth: '80px',
              backgroundColor: getButtonColor(),
              color: '#fff'
            }}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}

export default MacModal;