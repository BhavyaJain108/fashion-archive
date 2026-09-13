import { lookLabel, lookCounter, lookAlt } from './lookLabel';

describe('lookLabel', () => {
  it('zero-pads a single digit', () => {
    expect(lookLabel(7)).toBe('07');
  });

  it('leaves a two-digit number alone', () => {
    expect(lookLabel(34)).toBe('34');
  });

  it('never truncates a third digit', () => {
    expect(lookLabel(107)).toBe('107');
  });

  it('returns an empty string for null rather than "0NaN"', () => {
    expect(lookLabel(null)).toBe('');
  });

  it('returns an empty string for undefined rather than "0NaN"', () => {
    expect(lookLabel(undefined)).toBe('');
  });
});

describe('lookCounter', () => {
  it('pairs the padded number with the total', () => {
    expect(lookCounter(7, 38)).toBe('07 / 38');
  });
});

describe('lookAlt', () => {
  it('is not a bare number — it is read aloud, so it keeps a word', () => {
    const alt = lookAlt(7);
    expect(alt).toMatch(/[a-zA-Z]/);
    expect(alt).toContain('7');
  });

  it('names the designer when one is given', () => {
    expect(lookAlt(7, 'Gucci')).toContain('Gucci');
  });
});
