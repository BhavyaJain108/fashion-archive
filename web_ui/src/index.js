import React from 'react';
import ReactDOM from 'react-dom/client';

// This import MUST stay above `import App`.
//
// App transitively imports every feature stylesheet. The .ar-* primitives in
// archive.css and the feature classes collide at equal specificity, so
// whichever is injected last wins every tie. With App first, .ar-select beat
// .product-sort-select and the My Brands sort dropdown grew to the width of
// the toolbar while the search field collapsed to about 26 pixels.
//
// `npm run check:css` asserts this against the built bundle.
import './shared/styles/archive.css';
import App from './app/App';

// Suppress ResizeObserver errors (common with draggable components)
const originalError = console.error;
console.error = (...args) => {
  if (typeof args[0] === 'string' && args[0].includes('ResizeObserver')) {
    return; // Suppress ResizeObserver errors
  }
  originalError.apply(console, args);
};

// Suppress global error for ResizeObserver
window.addEventListener('error', (e) => {
  if (e.message && e.message.includes('ResizeObserver')) {
    e.preventDefault();
    return false;
  }
});

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);