import React, { useEffect, useState, useRef } from 'react';

function VideoModal({ videoPath, onClose }) {
  // Initialize position and size safely within viewport
  const [position, setPosition] = useState(() => {
    const safeX = typeof window !== 'undefined' ? Math.max(50, window.innerWidth - 450) : 50;
    const safeY = typeof window !== 'undefined' ? Math.max(100, Math.min(150, window.innerHeight - 400)) : 100;
    return { x: safeX, y: safeY };
  });
  const [size, setSize] = useState(() => ({
    width: 480,
    height: 310 // 480/(16/9) + 40 for title bar
  }));
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [resizeType, setResizeType] = useState(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const windowRef = useRef(null);

  // Handle escape key to close (matches tkinter behavior)
  useEffect(() => {
    const handleKeyPress = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [onClose]);

  // Resize functionality
  const handleResizeMouseDown = (e, type) => {
    e.stopPropagation();
    setIsResizing(true);
    setResizeType(type);
    setDragOffset({
      x: e.clientX,
      y: e.clientY,
      startWidth: size.width,
      startHeight: size.height,
      startX: position.x,
      startY: position.y
    });
  };

  // Dragging functionality (matches tkinter moveable window)
  const handleMouseDown = (e) => {
    if (windowRef.current && !isResizing) {
      const rect = windowRef.current.getBoundingClientRect();
      setDragOffset({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
      });
      setIsDragging(true);
    }
  };

  useEffect(() => {
    let rafId = null;
    
    const handleMouseMove = (e) => {
      if (isDragging) {
        // Use requestAnimationFrame to prevent ResizeObserver issues
        if (rafId) cancelAnimationFrame(rafId);
        
        rafId = requestAnimationFrame(() => {
          // Constrain window to viewport bounds
          const newX = Math.max(0, Math.min(window.innerWidth - size.width, e.clientX - dragOffset.x));
          const newY = Math.max(0, Math.min(window.innerHeight - 100, e.clientY - dragOffset.y));
          
          setPosition({ x: newX, y: newY });
        });
      } else if (isResizing) {
        if (rafId) cancelAnimationFrame(rafId);
        
        rafId = requestAnimationFrame(() => {
          const deltaX = e.clientX - dragOffset.x;
          const deltaY = e.clientY - dragOffset.y;
          const maxWidth = window.innerWidth * 0.5; // 50% screen width limit
          
          let newSize = { ...size };
          let newPosition = { ...position };
          
          if (resizeType === 'se') {
            // Southeast corner - resize maintaining aspect ratio
            const newWidth = Math.min(maxWidth, Math.max(300, dragOffset.startWidth + deltaX));
            const newHeight = (newWidth / (16/9)) + 40; // +40 for title bar
            newSize.width = newWidth;
            newSize.height = Math.max(250, newHeight);
          }
          
          setSize(newSize);
          setPosition(newPosition);
        });
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      setIsResizing(false);
      setResizeType(null);
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
    };

    if (isDragging || isResizing) {
      document.addEventListener('mousemove', handleMouseMove, { passive: true });
      document.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [isDragging, isResizing, dragOffset, size, position, resizeType]);

  return (
    <>
      {/* Video window - separate draggable window (matches tkinter separate window) */}
      <div 
        ref={windowRef}
        className="video-window" 
        style={{
          position: 'fixed',
          left: `${position.x}px`,
          top: `${position.y}px`,
          width: `${size.width}px`,
          height: `${size.height}px`,
          backgroundColor: '#c0c0c0',
          border: '2px outset #c0c0c0',
          boxShadow: '4px 4px 8px rgba(0,0,0,0.4)',
          zIndex: 2000,
          userSelect: 'none' // Prevent text selection during drag
        }}
      >
        {/* Title bar with drag handle */}
        <div 
          className="mac-title-bar" 
          onMouseDown={handleMouseDown}
          style={{ 
            display: 'flex', 
            justifyContent: 'space-between',
            cursor: isDragging ? 'grabbing' : 'grab',
            padding: '4px 8px',
            backgroundColor: '#c0c0c0',
            borderBottom: '1px solid #808080'
          }}
        >
          <span style={{ fontSize: '12px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: '8px' }}>{videoPath.title || 'Fashion Show Video'}</span>
          <button 
            onClick={onClose}
            className="mac-button"
            style={{ 
              padding: '0 6px',
              fontSize: '10px',
              minWidth: 'auto'
            }}
          >
            ✕
          </button>
        </div>
        
        {/* Video player - YouTube embed */}
        <div style={{ padding: '8px', height: 'calc(100% - 40px)', display: 'flex', flexDirection: 'column' }}>
          <iframe
            src={`${videoPath.embedUrl}?autoplay=1&rel=0&vq=hd1080`}
            title={videoPath.title || 'Fashion Show Video'}
            style={{
              display: 'block',
              width: '100%',
              height: '100%',
              border: '1px solid var(--mac-border)'
            }}
            allow="autoplay; encrypted-media"
            allowFullScreen
          />
        </div>
        
        {/* Invisible resize handle - corner only */}
        <div
          style={{
            position: 'absolute',
            right: 0,
            bottom: 0,
            width: '15px',
            height: '15px',
            cursor: 'se-resize',
            backgroundColor: 'transparent'
          }}
          onMouseDown={(e) => handleResizeMouseDown(e, 'se')}
        />
      </div>
    </>
  );
}

export default VideoModal;