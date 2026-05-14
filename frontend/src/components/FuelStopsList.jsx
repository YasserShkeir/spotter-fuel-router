import { fmtGallons, fmtMiles, fmtUSD } from '../lib/format.js'

export default function FuelStopsList({ fuel }) {
  if (!fuel?.stops?.length) {
    return (
      <div className="empty">
        <div className="empty__title">No refueling needed</div>
        <div>This trip fits in a single tank.</div>
      </div>
    )
  }
  return (
    <div className="stops-list">
      {fuel.stops.map((s, i) => (
        <div key={`${s.station.id}-${i}`} className="stops-list__item">
          <div
            className="stops-list__dot"
            style={{
              background: s.kind === 'origin_fillup' ? 'var(--stop-fillup)' : 'var(--stop-fuel)',
            }}
          />
          <div>
            <div className="stops-list__title">
              {s.kind === 'origin_fillup' ? 'Origin fillup · ' : ''}
              {s.station.name}
            </div>
            <div className="stops-list__sub">
              {s.station.city}, {s.station.state} · {s.station.address || '—'} · mi {fmtMiles(s.miles_along)}
            </div>
          </div>
          <div className="stops-list__meta">
            <div className="stops-list__price">{fmtUSD(s.cost_usd)}</div>
            <div>{fmtGallons(s.gallons_purchased)} @ {fmtUSD(s.price_per_gallon, { dp: 3 })}</div>
          </div>
        </div>
      ))}
    </div>
  )
}
