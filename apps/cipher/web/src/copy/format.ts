const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 });
const wholeDollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
export const money = (cents: number, whole = false) => {
  if (!Number.isSafeInteger(cents)) throw new Error('A monetary value is not safe integer cents.');
  const value = BigInt(cents);
  const absolute = value < 0n ? -value : value;
  const amount = whole ? (absolute + 50n) / 100n : absolute / 100n;
  const fraction = (absolute % 100n).toString().padStart(2, '0');
  const parts = (whole ? wholeDollars : dollars).formatToParts(amount);
  return (value < 0n ? '-' : '') + parts.map(part => part.type === 'fraction' ? fraction : part.value).join('');
};
export const date = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? 'Date unavailable' : new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(parsed);
};
export const rate = (micros: number) => `${(micros / 10_000).toFixed(1)}%`;

export const sumCents = (values: Iterable<number>) => {
  let total = 0n;
  for (const value of values) {
    if (!Number.isSafeInteger(value)) throw new Error('A monetary value is not safe integer cents.');
    total += BigInt(value);
  }
  if (total > BigInt(Number.MAX_SAFE_INTEGER) || total < BigInt(Number.MIN_SAFE_INTEGER)) {
    throw new Error('A practice total is outside the supported monetary range.');
  }
  return Number(total);
};
