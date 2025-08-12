import React from 'react';

function SeasonsPanel({ seasons, selectedSeason, onSeasonSelect }) {
  return (
    <div className="mac-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Title - matches tkinter */}
      <div className="mac-label title">
        Fashion Seasons
      </div>

      {/* Seasons List - matches tkinter listbox */}
      <div className="mac-listbox mac-scrollbar" style={{ flex: 1, margin: '8px 0' }}>
        {seasons.length === 0 ? (
          <div className="mac-listbox-item">Loading seasons...</div>
        ) : (
          seasons.map((season, index) => (
            <div
              key={index}
              className={`mac-listbox-item ${selectedSeason === season ? 'selected' : ''}`}
              onClick={() => onSeasonSelect(season)}
            >
              📅 {season.name}
            </div>
          ))
        )}
      </div>

      {/* View Collections Button - matches tkinter button */}
      <div style={{ padding: '8px' }}>
        <button 
          className="mac-button" 
          style={{ width: '100%' }}
          disabled={!selectedSeason}
          onClick={() => selectedSeason && onSeasonSelect(selectedSeason)}
        >
          View Collections
        </button>
      </div>
    </div>
  );
}

export default SeasonsPanel;