import React, { useState } from 'react';
import { FashionArchiveAPI } from '../services/api';

function MenuBar({ currentPage, onPageSwitch, currentView, onViewChange }) {
  const [showToolsMenu, setShowToolsMenu] = useState(false);
  const [showPagesMenu, setShowPagesMenu] = useState(false);
  const [showViewMenu, setShowViewMenu] = useState(false);
  const [showAbout, setShowAbout] = useState(false);
  const [aboutInfo, setAboutInfo] = useState(null);
  const [videoTestOpen, setVideoTestOpen] = useState(false);
  const [testQuery, setTestQuery] = useState('');
  const [testResults, setTestResults] = useState(null);
  const [researchMode, setResearchMode] = useState(false);

  // Show Tools menu dropdown
  const handleToolsClick = () => {
    setShowToolsMenu(!showToolsMenu);
    setShowPagesMenu(false); // Close other menus
    setShowViewMenu(false);
  };

  // Show Pages menu dropdown
  const handlePagesClick = () => {
    setShowPagesMenu(!showPagesMenu);
    setShowToolsMenu(false); // Close other menus
    setShowViewMenu(false);
  };

  // Show View menu dropdown
  const handleViewClick = () => {
    setShowViewMenu(!showViewMenu);
    setShowToolsMenu(false); // Close other menus
    setShowPagesMenu(false);
  };

  // Show About dialog (matches tkinter show_about)
  const handleAboutClick = async () => {
    setShowToolsMenu(false);
    setShowPagesMenu(false);
    setShowViewMenu(false);
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
    setShowPagesMenu(false);
    setShowViewMenu(false);
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

  // Toggle research mode
  const handleResearchToggle = () => {
    setResearchMode(!researchMode);
    setShowToolsMenu(false);
    setShowPagesMenu(false);
    setShowViewMenu(false);
  };

  // Pages menu handlers - page navigation
  const handleHighFashionPage = () => {
    setShowPagesMenu(false);
    onPageSwitch('high-fashion');
  };

  const handleFavouritesPage = () => {
    setShowPagesMenu(false);
    onPageSwitch('favourites');
  };

  // View menu handlers - view mode changes for current page
  const handleViewChange = (viewMode) => {
    setShowViewMenu(false);
    onViewChange(viewMode);
  };

  // Get view options based on current page
  const getViewOptions = () => {
    switch (currentPage) {
      case 'high-fashion':
        return [
          { key: 'standard', label: 'Standard View' }
        ];
      case 'favourites':
        return [
          { key: 'view-all', label: 'View All' },
          { key: 'by-collection', label: 'By Collection' }
        ];
      case 'my-brands':
        return [
          { key: 'all-brands', label: 'All Brands' },
          { key: 'brand-products', label: 'Products' }
        ];
      default:
        return [];
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
        <div onClick={handleToolsClick}
             style={{ 
               padding: '2px 8px', 
               cursor: 'pointer',
               position: 'relative',
               backgroundColor: showToolsMenu ? '#e0e0e0' : 'transparent',
               color: '#000'
             }}
             onMouseEnter={(e) => {
               if (!showToolsMenu) {
                 e.target.style.backgroundColor = '#d0d0d0';
               }
             }}
             onMouseLeave={(e) => {
               if (!showToolsMenu) {
                 e.target.style.backgroundColor = 'transparent';
               }
             }}
        >
          Tools
          
          {/* Tools Dropdown Menu */}
          {showToolsMenu && (
            <div style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              backgroundColor: '#f0f0f0',
              border: '1px solid #ccc',
              borderTop: 'none',
              minWidth: '150px',
              zIndex: 1001,
              boxShadow: '2px 2px 4px rgba(0,0,0,0.1)'
            }}>
              <div onClick={handleResearchToggle}
                   style={{ 
                     padding: '6px 12px', 
                     cursor: 'pointer',
                     borderBottom: '1px solid #ddd',
                     display: 'flex',
                     justifyContent: 'space-between',
                     alignItems: 'center',
                     backgroundColor: 'transparent',
                     color: '#000'
                   }}
                   onMouseEnter={(e) => e.target.style.backgroundColor = '#d0d0d0'}
                   onMouseLeave={(e) => e.target.style.backgroundColor = 'transparent'}
              >
                <span>Research</span>
                <span style={{ fontSize: '12px', fontWeight: 'bold' }}>
                  {researchMode ? '✓' : ''}
                </span>
              </div>
              <div onClick={handleVideoTest}
                   style={{ 
                     padding: '6px 12px', 
                     cursor: 'pointer',
                     borderBottom: '1px solid #ddd',
                     backgroundColor: 'transparent',
                     color: '#000'
                   }}
                   onMouseEnter={(e) => e.target.style.backgroundColor = '#d0d0d0'}
                   onMouseLeave={(e) => e.target.style.backgroundColor = 'transparent'}
              >
                Video Search Test
              </div>
              <div onClick={handleAboutClick}
                   style={{ 
                     padding: '6px 12px', 
                     cursor: 'pointer',
                     backgroundColor: 'transparent',
                     color: '#000'
                   }}
                   onMouseEnter={(e) => e.target.style.backgroundColor = '#d0d0d0'}
                   onMouseLeave={(e) => e.target.style.backgroundColor = 'transparent'}
              >
                About
              </div>
            </div>
          )}
        </div>

        {/* Pages Menu */}
        <div onClick={handlePagesClick}
             style={{ 
               padding: '2px 8px', 
               cursor: 'pointer',
               position: 'relative',
               backgroundColor: showPagesMenu ? '#e0e0e0' : 'transparent',
               color: '#000'
             }}
             onMouseEnter={(e) => {
               if (!showPagesMenu) {
                 e.target.style.backgroundColor = '#d0d0d0';
               }
             }}
             onMouseLeave={(e) => {
               if (!showPagesMenu) {
                 e.target.style.backgroundColor = 'transparent';
               }
             }}
        >
          Pages
          
          {/* Pages Dropdown Menu */}
          {showPagesMenu && (
            <div style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              backgroundColor: '#f0f0f0',
              border: '1px solid #ccc',
              borderTop: 'none',
              minWidth: '150px',
              zIndex: 1001,
              boxShadow: '2px 2px 4px rgba(0,0,0,0.1)'
            }}>
              <div onClick={handleHighFashionPage}
                   style={{ 
                     padding: '6px 12px', 
                     cursor: 'pointer',
                     borderBottom: '1px solid #ddd',
                     backgroundColor: 'transparent',
                     color: '#000'
                   }}
                   onMouseEnter={(e) => e.target.style.backgroundColor = '#d0d0d0'}
                   onMouseLeave={(e) => e.target.style.backgroundColor = 'transparent'}
              >
                High Fashion
              </div>
              <div onClick={handleFavouritesPage}
                   style={{ 
                     padding: '6px 12px', 
                     cursor: 'pointer',
                     borderBottom: '1px solid #ddd',
                     backgroundColor: 'transparent',
                     color: '#000'
                   }}
                   onMouseEnter={(e) => e.target.style.backgroundColor = '#d0d0d0'}
                   onMouseLeave={(e) => e.target.style.backgroundColor = 'transparent'}
              >
                Favourites
              </div>
              <div onClick={() => {
                setShowPagesMenu(false);
                onPageSwitch('my-brands');
              }}
                   style={{ 
                     padding: '6px 12px', 
                     cursor: 'pointer',
                     backgroundColor: 'transparent',
                     color: '#000'
                   }}
                   onMouseEnter={(e) => e.target.style.backgroundColor = '#d0d0d0'}
                   onMouseLeave={(e) => e.target.style.backgroundColor = 'transparent'}
              >
                My Brands
              </div>
            </div>
          )}
        </div>

        {/* View Menu */}
        <div onClick={handleViewClick}
             style={{ 
               padding: '2px 8px', 
               cursor: 'pointer',
               position: 'relative',
               backgroundColor: showViewMenu ? '#e0e0e0' : 'transparent',
               color: '#000'
             }}
             onMouseEnter={(e) => {
               if (!showViewMenu) {
                 e.target.style.backgroundColor = '#d0d0d0';
               }
             }}
             onMouseLeave={(e) => {
               if (!showViewMenu) {
                 e.target.style.backgroundColor = 'transparent';
               }
             }}
        >
          View
          
          {/* View Dropdown Menu */}
          {showViewMenu && (
            <div style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              backgroundColor: '#f0f0f0',
              border: '1px solid #ccc',
              borderTop: 'none',
              minWidth: '150px',
              zIndex: 1001,
              boxShadow: '2px 2px 4px rgba(0,0,0,0.1)'
            }}>
              {getViewOptions().map((option, index) => (
                <div 
                  key={option.key}
                  onClick={() => handleViewChange(option.key)}
                  style={{ 
                    padding: '6px 12px', 
                    cursor: 'pointer',
                    borderBottom: index < getViewOptions().length - 1 ? '1px solid #ddd' : 'none',
                    backgroundColor: 'transparent',
                    color: '#000',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center'
                  }}
                  onMouseEnter={(e) => e.target.style.backgroundColor = '#d0d0d0'}
                  onMouseLeave={(e) => e.target.style.backgroundColor = 'transparent'}
                >
                  <span>{option.label}</span>
                  <span style={{ fontSize: '12px', fontWeight: 'bold' }}>
                    {currentView === option.key ? '✓' : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Click outside to close menus */}
      {(showToolsMenu || showPagesMenu || showViewMenu) && (
        <div 
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 999
          }}
          onClick={() => {
            setShowToolsMenu(false);
            setShowPagesMenu(false);
            setShowViewMenu(false);
          }}
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