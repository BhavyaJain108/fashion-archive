import { convert, formatMoney, guessCurrency, priceText } from './money';

const RATES = { USD: 1, EUR: 0.88, GBP: 0.76, INR: 96, AUD: 1.42 };

test('a region names its currency, and an unknown one pays in dollars', () => {
  expect(guessCurrency('en-IN')).toBe('INR');
  expect(guessCurrency('de-DE')).toBe('EUR');
  expect(guessCurrency('en')).toBe('USD');
  expect(guessCurrency('xx-ZZ')).toBe('USD');
});

test('conversion goes through the dollar and is honest when a rate is missing', () => {
  expect(convert(88, 'EUR', 'USD', RATES)).toBeCloseTo(100);
  expect(convert(100, 'USD', 'INR', RATES)).toBe(9600);
  expect(convert(100, 'RUB', 'USD', RATES)).toBeNull();
  expect(convert('1,200.00', 'USD', 'USD', RATES)).toBe(1200);
});

test('a price reads in the visitor currency, marked approximate, or as the shop prints it', () => {
  expect(priceText(88, 'EUR', 'USD', RATES)).toBe('≈ $100');
  expect(priceText(88, 'EUR', 'EUR', RATES)).toBe('€88');
  expect(priceText(2000, 'RUB', 'USD', RATES).replace(/\u00a0/g, ' ')).toBe('RUB 2,000');
  expect(priceText(12.5, 'USD', 'USD', RATES)).toBe('$12.50');
  expect(formatMoney(null, 'USD')).toBe('');
});
