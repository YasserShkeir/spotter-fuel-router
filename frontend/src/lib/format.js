export function fmtUSD(n, { dp = 2 } = {}) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return n.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  })
}

export function fmtNumber(n, { dp = 1 } = {}) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return n.toLocaleString('en-US', {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  })
}

export function fmtMiles(n) {
  return `${fmtNumber(n, { dp: 0 })} mi`
}

export function fmtGallons(n) {
  return `${fmtNumber(n, { dp: 1 })} gal`
}

export const STRATEGY_LABELS = {
  look_ahead: 'Look-ahead (smart)',
  cheapest_fill_full: 'Cheapest, fill to full',
  furthest_fill_full: 'Furthest reachable',
}

export const STRATEGY_BLURBS = {
  look_ahead:
    'Picks the cheapest reachable station and buys only what it needs to reach a cheaper one ahead. Fills a minimum of 10 gallons per stop.',
  cheapest_fill_full:
    'Picks the cheapest reachable station but always fills to full — overpays a bit when a cheaper place is ahead.',
  furthest_fill_full:
    'Naive baseline — stops as far as fuel allows, ignores price. Fewer stops, most expensive total.',
}

export const TANK_LABELS = {
  full_free: 'Free starting tank',
  fillup_at_origin: 'Fill up at origin',
}

export const TANK_BLURBS = {
  full_free:
    'The truck leaves with a full tank that isn\'t counted in the cost (fleet dispatcher view).',
  fillup_at_origin:
    'Pay for an initial 50-gal fillup at the nearest station to the origin.',
}
