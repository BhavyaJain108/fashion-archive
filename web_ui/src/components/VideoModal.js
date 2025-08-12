import React, { useEffect, useState, useRef } from 'react';
import { FashionArchiveAPI } from '../services/api';

function VideoModal({ videoPath, onClose }) {
  // Initialize position safely within viewport
  const [position, setPosition] = useState(() => {
    const safeX = typeof window !== 'undefined' ? Math.max(50, window.innerWidth - 450) : 50;
    const safeY = typeof window !== 'undefined' ? Math.max(100, Math.min(150, window.innerHeight - 400)) : 100;
    return { x: safeX, y: safeY };
  });
  const [isDragging, setIsDragging] = useState(false);
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

  // Dragging functionality (matches tkinter moveable window)
  const handleMouseDown = (e) => {
    if (windowRef.current) {
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
          const newX = Math.max(0, Math.min(window.innerWidth - 400, e.clientX - dragOffset.x));
          const newY = Math.max(0, Math.min(window.innerHeight - 100, e.clientY - dragOffset.y));
          
          setPosition({ x: newX, y: newY });
        });
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
    };

    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove, { passive: true });
      document.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [isDragging, dragOffset]);

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
          backgroundColor: 'var(--mac-bg)',
          border: '2px outset var(--mac-bg)',
          boxShadow: '4px 4px 8px rgba(0,0,0,0.4)',
          zIndex: 2000,
          minWidth: '400px',
          maxWidth: '800px',
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
            backgroundColor: 'var(--mac-bg)',
            borderBottom: '1px solid var(--mac-border)'
          }}
        >
          <span style={{ fontSize: '12px' }}>Fashion Show Video</span>
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
        
        {/* Video player - simple HTML5 video */}
        <div style={{ padding: '8px' }}>
          <video 
            controls 
            autoPlay
            style={{ 
              display: 'block',
              maxWidth: '760px',
              maxHeight: '500px',
              width: '100%',
              border: '1px solid var(--mac-border)'
            }}
          >
            <source src={FashionArchiveAPI.getVideoUrl(videoPath)} type="video/mp4" />
            Your browser does not support the video tag.
          </video>
        </div>
      </div>
    </>
  );
}

export default VideoModal;