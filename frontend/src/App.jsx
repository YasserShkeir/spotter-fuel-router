import { useEffect, useState } from 'react'
import { api } from './api/client.js'
import CostSummary from './components/CostSummary.jsx'
import FuelStopsList from './components/FuelStopsList.jsx'
import RouteMap from './components/RouteMap.jsx'
import StrategyCompare from './components/StrategyCompare.jsx'
import TripForm from './components/TripForm.jsx'

const STRATEGIES = ['look_ahead', 'cheapest_fill_full', 'furthest_fill_full']

export default function App() {
  const [data, setData] = useState(null)
  const [comparison, setComparison] = useState(null)
  const [error, setError] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [tab, setTab] = useState('map')

  // Fire-and-forget wake-up to Render's free-tier container while the
  // user reads the page or types into the form — saves them the ~30 s
  // cold-start tax on the first "Plan" click.
  useEffect(() => {
    fetch('/healthz', { method: 'GET' }).catch(() => {})
  }, [])

  async function plan(payload) {
    setIsLoading(true)
    setError(null)
    setComparison(null)
    try {
      const result = await api.planRoute(payload)
      setData(result)
      setTab('map')
    } catch (err) {
      setError(err.message || String(err))
    } finally {
      setIsLoading(false)
    }
  }

  async function compare(basePayload) {
    setIsLoading(true)
    setError(null)
    setData(null)
    try {
      // Fan out one request per strategy in parallel. Each carries the same
      // start/finish but a different refuel_strategy override.
      const all = await Promise.all(
        STRATEGIES.map((s) =>
          api
            .planRoute({
              ...basePayload,
              options: { ...basePayload.options, refuel_strategy: s },
            })
            .then((r) => ({ strategy: s, ...r }))
            .catch((err) => ({ strategy: s, error: err.message || String(err) })),
        ),
      )
      setComparison(all)
      // Show the cheapest plan's map by default.
      const best = all
        .filter((r) => !r.error)
        .reduce(
          (a, b) =>
            !a || (b.fuel.total_fuel_cost_usd < a.fuel.total_fuel_cost_usd) ? b : a,
          null,
        )
      if (best) setData(best)
      setTab('compare')
    } catch (err) {
      setError(err.message || String(err))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="app__header">
        <div className="brand">
          <div className="brand__mark">FR</div>
          <div>
            <div className="brand__name">Spotter Fuel Router</div>
            <span className="brand__tag">cheapest-route planner</span>
          </div>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-3)' }}>
          Routes via{' '}
          <a href="https://routing.openstreetmap.de" target="_blank" rel="noreferrer">OSRM</a>
          {' · '}
          Maps ©{' '}
          <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
            OpenStreetMap
          </a>
        </div>
      </header>

      <div className="app__main">
        <aside className="sidebar">
          <h1 style={{ marginBottom: 4 }}>Plan a trip</h1>
          <p style={{ color: 'var(--text-3)', marginBottom: 20 }}>
            Pick a start and finish. We'll route via OSRM and pick the cheapest
            fuel stops from 7,530 real US truckstop prices.
          </p>
          <TripForm onPlan={plan} onCompare={compare} isLoading={isLoading} />

          {error ? (
            <div className="banner banner--error" style={{ marginTop: 20 }}>
              <strong>Could not plan that trip.</strong>
              <div>{error}</div>
            </div>
          ) : null}

          <div style={{ marginTop: 24, fontSize: 12, color: 'var(--text-3)' }}>
            <h4 style={{ marginBottom: 8 }}>Assumptions</h4>
            <ul style={{ paddingLeft: 18, margin: 0, lineHeight: 1.7 }}>
              <li>Vehicle range: 500 mi on a full tank</li>
              <li>Fuel economy: 10 mpg</li>
              <li>One OSRM call per plan (per the assessment spec)</li>
              <li>Prices: from the supplied OPIS truckstop CSV (US only)</li>
            </ul>
          </div>
        </aside>

        <main className="workspace">
          {!data && !comparison ? (
            <EmptyState />
          ) : (
            <>
              {comparison ? (
                <div className="card">
                  <div className="card__header">
                    <span className="card__title">Strategy comparison</span>
                    <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
                      Same route, three planners, run in parallel.
                    </span>
                  </div>
                  <div className="card__body">
                    <StrategyCompare results={comparison} />
                  </div>
                </div>
              ) : null}

              {data ? (
                <>
                  <CostSummary route={data.route} fuel={data.fuel} meta={data.meta} />
                  <div className="card">
                    <div className="card__body card__body--flush">
                      <div className="tabs">
                        <button
                          className={`tab ${tab === 'map' ? 'tab--active' : ''}`}
                          onClick={() => setTab('map')}
                        >
                          Route map
                        </button>
                        <button
                          className={`tab ${tab === 'stops' ? 'tab--active' : ''}`}
                          onClick={() => setTab('stops')}
                        >
                          Fuel stops
                        </button>
                      </div>
                      <div style={{ padding: 20 }}>
                        {tab === 'map' ? (
                          <RouteMap inputs={data.inputs} route={data.route} fuel={data.fuel} />
                        ) : (
                          <FuelStopsList fuel={data.fuel} />
                        )}
                      </div>
                    </div>
                  </div>
                </>
              ) : null}
            </>
          )}
        </main>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="card">
      <div className="card__body">
        <div className="empty">
          <div style={{ fontSize: 36, marginBottom: 12 }}>⛽</div>
          <div className="empty__title">Pick a start and finish</div>
          <div>
            Or hit <span className="kbd">Try a sample trip</span> to see
            Chicago → Houston with all three strategies on the map.
          </div>
        </div>
      </div>
    </div>
  )
}
