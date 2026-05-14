import { STRATEGY_LABELS, TANK_LABELS, fmtGallons, fmtMiles, fmtUSD } from '../lib/format.js'

export default function CostSummary({ route, fuel, meta }) {
  if (!route || !fuel) return null
  return (
    <div className="summary-grid">
      <div className="stat">
        <span className="stat__label">Route distance</span>
        <span className="stat__value">{fmtMiles(route.distance_miles)}</span>
        <span className="stat__sub">{Math.round(route.duration_seconds / 60)} min driving</span>
      </div>
      <div className="stat stat--accent">
        <span className="stat__label">Total fuel cost</span>
        <span className="stat__value">{fmtUSD(fuel.total_fuel_cost_usd)}</span>
        <span className="stat__sub">{fmtGallons(fuel.total_fuel_gallons)} purchased</span>
      </div>
      <div className="stat">
        <span className="stat__label">Refuels</span>
        <span className="stat__value">{fuel.stops.length}</span>
        <span className="stat__sub">{STRATEGY_LABELS[fuel.refuel_strategy] || fuel.refuel_strategy}</span>
      </div>
      <div className="stat">
        <span className="stat__label">Starting tank</span>
        <span className="stat__value" style={{ fontSize: 15 }}>
          {TANK_LABELS[fuel.starting_tank] || fuel.starting_tank}
        </span>
        <span className="stat__sub">{meta?.elapsed_ms ? `${Math.round(meta.elapsed_ms)} ms` : ''}</span>
      </div>
    </div>
  )
}
