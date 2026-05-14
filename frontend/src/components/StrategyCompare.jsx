import { STRATEGY_LABELS, fmtGallons, fmtUSD } from '../lib/format.js'

export default function StrategyCompare({ results }) {
  if (!results?.length) return null
  const validResults = results.filter((r) => !r.error)
  if (!validResults.length) {
    return (
      <div className="banner banner--error">
        All three strategies failed to plan a trip — try a different route.
      </div>
    )
  }
  const cheapestCost = Math.min(...validResults.map((r) => r.fuel.total_fuel_cost_usd))

  return (
    <div className="compare-grid">
      {results.map((r) => {
        if (r.error) {
          return (
            <div key={r.strategy} className="compare-card">
              <span className="compare-card__label">{STRATEGY_LABELS[r.strategy]}</span>
              <span className="compare-card__name">Failed</span>
              <span className="compare-card__meta">{r.error}</span>
            </div>
          )
        }
        const cost = r.fuel.total_fuel_cost_usd
        const isBest = cost === cheapestCost
        const delta = cost - cheapestCost
        return (
          <div key={r.strategy} className={`compare-card ${isBest ? 'compare-card--best' : ''}`}>
            <span className="compare-card__label">{STRATEGY_LABELS[r.strategy]}</span>
            {isBest ? <span className="compare-card__badge">Cheapest</span> : null}
            <span className="compare-card__cost">{fmtUSD(cost)}</span>
            <span
              className={
                isBest
                  ? 'compare-card__delta compare-card__delta--save'
                  : 'compare-card__delta compare-card__delta--extra'
              }
            >
              {isBest ? 'Baseline' : `+${fmtUSD(delta)} vs cheapest`}
            </span>
            <span className="compare-card__meta">
              {r.fuel.stops.length} stops · {fmtGallons(r.fuel.total_fuel_gallons)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
