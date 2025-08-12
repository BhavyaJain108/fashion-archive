import React, { useState } from 'react';
import { FashionArchiveAPI } from '../services/api';

function MenuBar() {
  const [showToolsMenu, setShowToolsMenu] = useState(false);
  const [showAbout, setShowAbout] = useState(false);
  const [aboutInfo, setAboutInfo] = useState(null);
  const [videoTestOpen, setVideoTestOpen] = useState(false);
  const [testQuery, setTestQuery] = useState('');
  const [testResults, setTestResults] = useState(null);

  // Show Tools menu dropdown
  const handleToolsClick = () => {
    setShowToolsMenu(!showToolsMenu);
  };

  // Show About dialog (matches tkinter show_about)
  const handleAboutClick = async () => {
    setShowToolsMenu(false);
    try {
      const info = await FashionArchiveAPI.getAboutInfo();
      setAboutInfo(info);
      setShowAbout(true);
    } catch (error) {
      console.error('Error loading about info:', error);
    }
  };

  // Open video search test (matches tkinter open_video_test)
  const handleVideoTest = () => {
    setShowToolsMenu(false);
    setVideoTestOpen(true);
    setTestQuery('');
    setTestResults(null);
  };

  // Run video search test
  const runVideoTest = async () => {
    if (!testQuery.trim()) return;
    
    try {
      const results = await FashionArchiveAPI.testVideoSearch(testQuery);
      setTestResults(results);
    } catch (error) {
      console.error('Video test error:', error);
      setTestResults({ success: false, error: error.message });
    }
  };

  return (
    <>
      {/* Menu Bar (matches tkinter menu system) */}
      <div className="mac-menubar" style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: '20px',
        backgroundColor: 'var(--mac-bg)',
        borderBottom: '1px solid var(--mac-border)',
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        fontSize: '12px',
        paddingLeft: '8px'
      }}>
        <div className="mac-menu-item" 
             onClick={handleToolsClick}
             style={{ 
               padding: '2px 8px', 
               cursor: 'pointer',
               position: 'relative' 
             }}
        >
          Tools
          
          {/* Tools Dropdown Menu */}
          {showToolsMenu && (
            <div className="mac-dropdown" style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              backgroundColor: 'white',
              border: '2px outset var(--mac-bg)',
              minWidth: '150px',
              zIndex: 1001
            }}>
              <div className="mac-menu-option" 
                   onClick={handleVideoTest}
                   style={{ 
                     padding: '4px 12px', 
                     cursor: 'pointer',
                     borderBottom: '1px solid var(--mac-border)'
                   }}
              >
                Video Search Test
              </div>
              <div className="mac-menu-option" 
                   onClick={handleAboutClick}
                   style={{ 
                     padding: '4px 12px', 
                     cursor: 'pointer' 
                   }}
              >
                About
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Click outside to close menu */}
      {showToolsMenu && (
        <div 
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 999
          }}
          onClick={() => setShowToolsMenu(false)}
        />
      )}

      {/* About Dialog (matches tkinter About dialog) */}
      {showAbout && aboutInfo && (
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
            <h3 style={{ margin: '0 0 12px 0', textAlign: 'center' }}>
              {aboutInfo.name}
            </h3>
            <div style={{ marginBottom: '12px' }}>
              <strong>Version:</strong> {aboutInfo.version}
            </div>
            <div style={{ marginBottom: '12px' }}>
              <strong>Description:</strong> {aboutInfo.description}
            </div>
            <div style={{ marginBottom: '12px' }}>
              <strong>Migration:</strong> {aboutInfo.original}
            </div>
            <div style={{ marginBottom: '16px' }}>
              <strong>Features:</strong>
              <ul style={{ margin: '4px 0', paddingLeft: '20px' }}>
                {aboutInfo.features.map((feature, index) => (
                  <li key={index} style={{ margin: '2px 0' }}>{feature}</li>
                ))}
              </ul>
            </div>
            <div style={{ textAlign: 'center' }}>
              <button 
                className="mac-button"
                onClick={() => setShowAbout(false)}
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Video Search Test Dialog (matches tkinter video search test popup) */}
      {videoTestOpen && (
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
            minWidth: '450px',
            maxWidth: '600px',
            maxHeight: '400px'
          }}>
            <h3 style={{ margin: '0 0 12px 0' }}>Video Search Test</h3>
            
            <div style={{ marginBottom: '12px' }}>
              <label style={{ display: 'block', marginBottom: '4px' }}>
                Search Query:
              </label>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input 
                  type="text"
                  value={testQuery}
                  onChange={(e) => setTestQuery(e.target.value)}
                  className="mac-input"
                  style={{ flex: 1 }}
                  placeholder="Enter fashion collection search query..."
                  onKeyPress={(e) => {
                    if (e.key === 'Enter') runVideoTest();
                  }}
                />
                <button 
                  className="mac-button"
                  onClick={runVideoTest}
                  disabled={!testQuery.trim()}
                >
                  Test Search
                </button>
              </div>
            </div>

            {/* Test Results */}
            {testResults && (
              <div style={{ marginBottom: '12px' }}>
                <strong>Results:</strong>
                <div className="mac-panel" style={{ 
                  padding: '8px', 
                  margin: '4px 0',
                  maxHeight: '200px',
                  overflow: 'auto',
                  fontSize: '11px'
                }}>
                  {testResults.success ? (
                    testResults.results ? (
                      <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                        {JSON.stringify(testResults.results, null, 2)}
                      </pre>
                    ) : (
                      'No results found'
                    )
                  ) : (
                    <div style={{ color: 'red' }}>
                      Error: {testResults.error}
                    </div>
                  )}
                </div>
              </div>
            )}

            <div style={{ textAlign: 'center', display: 'flex', gap: '8px', justifyContent: 'center' }}>
              <button 
                className="mac-button"
                onClick={() => {
                  setVideoTestOpen(false);
                  setTestResults(null);
                  setTestQuery('');
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default MenuBar;