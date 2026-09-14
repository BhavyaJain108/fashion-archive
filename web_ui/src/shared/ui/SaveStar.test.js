import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import SaveStar from './SaveStar';

// The component's own contract. The four sites are tested where they live —
// saveStars.test.js — because what matters there is which target each one
// names and whose click it must not become.

test('it is a button, not a div with a handler', () => {
  render(<SaveStar saved={false} onToggle={() => {}} label="Save this show" />);
  const star = screen.getByRole('button', { name: 'Save this show' });
  // The whole of keyboard support is this tag: in the tab order, activated by
  // Enter and by Space, with no key handler anywhere in this file.
  expect(star.tagName).toBe('BUTTON');
  expect(star).toHaveAttribute('type', 'button');
});

test('it says whether it is on', () => {
  const { rerender } = render(<SaveStar saved={false} onToggle={() => {}} label="Save look 3" />);
  const star = screen.getByRole('button', { name: 'Save look 3' });
  expect(star).toHaveAttribute('aria-pressed', 'false');
  expect(star).toHaveTextContent('☆');

  rerender(<SaveStar saved onToggle={() => {}} label="Save look 3" />);
  expect(star).toHaveAttribute('aria-pressed', 'true');
  expect(star).toHaveTextContent('★');
});

// The name is the thing being saved, not the verb. A reader who cannot see
// which row the star is on has nothing else to tell four identical stars
// apart, and the glyph itself is aria-hidden.
test('the label names what is being saved', () => {
  render(
    <>
      <SaveStar saved={false} onToggle={() => {}} label="Save this show — Yohji Yamamoto" />
      <SaveStar saved={false} onToggle={() => {}} label="Save look 12" />
      <SaveStar saved={false} onToggle={() => {}} label="Save this view" />
    </>
  );
  expect(screen.getByRole('button', { name: 'Save this show — Yohji Yamamoto' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save look 12' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save this view' })).toBeInTheDocument();
});

test('one click toggles, with nothing in between', () => {
  const onToggle = jest.fn();
  render(<SaveStar saved={false} onToggle={onToggle} label="Save look 3" />);
  fireEvent.click(screen.getByRole('button', { name: 'Save look 3' }));
  expect(onToggle).toHaveBeenCalledTimes(1);
  // No dialog, no menu, no second step.
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.queryByRole('menu')).toBeNull();
});

// The single most likely defect in this task: a star inside something that
// is itself clickable.
test('the click stops at the star', () => {
  const onToggle = jest.fn();
  const parent = jest.fn();
  render(
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events
    <div onClick={parent} onMouseDown={parent}>
      <SaveStar saved={false} onToggle={onToggle} label="Save look 3" />
    </div>
  );
  const star = screen.getByRole('button', { name: 'Save look 3' });
  fireEvent.mouseDown(star);
  fireEvent.click(star);
  expect(onToggle).toHaveBeenCalledTimes(1);
  expect(parent).not.toHaveBeenCalled();
});

test('disabled is inert and says so', () => {
  const onToggle = jest.fn();
  render(<SaveStar saved={false} onToggle={onToggle} label="Save this view" disabled />);
  const star = screen.getByRole('button', { name: 'Save this view' });
  expect(star).toBeDisabled();
  fireEvent.click(star);
  expect(onToggle).not.toHaveBeenCalled();
});

// The no-reflow guarantee is one box on one class, and no site may size its
// own star. Measured for real in headless Chrome as well — see the task
// report — but this is what keeps it true as the sites change.
test('the box is the class, in both states and at both sizes', () => {
  const { rerender } = render(<SaveStar saved={false} onToggle={() => {}} label="s" />);
  const star = screen.getByRole('button', { name: 's' });
  expect(star).toHaveClass('ar-star');
  expect(star.getAttribute('style')).toBeNull();

  rerender(<SaveStar saved onToggle={() => {}} label="s" size="sm" className="hf2-row-star" />);
  expect(star).toHaveClass('ar-star', 'sm', 'on', 'hf2-row-star');
  expect(star.getAttribute('style')).toBeNull();
});

test('the stylesheet never lets a site resize a star', () => {
  const fs = require('fs');
  const path = require('path');
  const css = fs.readFileSync(path.join(__dirname, 'SaveStar.css'), 'utf8');
  // The box lives once, on .ar-star, and it is what reserves the space.
  const base = css.slice(css.indexOf('.ar-star {'), css.indexOf('.ar-star.sm'));
  expect(base).toMatch(/width: var\(--ar-star-box\)/);
  expect(base).toMatch(/height: var\(--ar-star-box\)/);
  expect(base).toMatch(/flex: 0 0 auto/);
  // And no --ar-danger in any declaration: that colour means a destructive
  // confirmation, and a star is neither destructive nor a confirmation.
  // Comments stripped first — the rule is about what renders, and the file
  // says in prose why the colour is not here.
  const declarations = css.replace(/\/\*[\s\S]*?\*\//g, '');
  expect(declarations).not.toContain('--ar-danger');
  expect(declarations).not.toContain('#cc0000');
});
