import { useState } from 'react'
import LocationInput from './LocationInput.jsx'
import StrategyPicker from './StrategyPicker.jsx'

const SAMPLE = {
  start: { label: 'Chicago, IL', lat: 41.8781, lon: -87.6298 },
  finish: { label: 'Houston, TX', lat: 29.7604, lon: -95.3698 },
}

export default function TripForm({ onPlan, onCompare, isLoading }) {
  const [start, setStart] = useState(null)
  const [finish, setFinish] = useState(null)
  const [strategy, setStrategy] = useState('look_ahead')
  const [tank, setTank] = useState('full_free')

  function locationPayload(loc) {
    if (!loc) return null
    if (loc.lat !== undefined && loc.lon !== undefined) {
      return { label: loc.label, lat: loc.lat, lon: loc.lon }
    }
    return { query: loc.label }
  }

  function canSubmit() {
    return !!start?.label?.trim() && !!finish?.label?.trim() && !isLoading
  }

  function buildPayload() {
    return {
      start: locationPayload(start),
      finish: locationPayload(finish),
      options: { refuel_strategy: strategy, starting_tank: tank },
    }
  }

  function submit(e) {
    e.preventDefault()
    if (!canSubmit()) return
    onPlan(buildPayload())
  }

  function compare() {
    if (!canSubmit()) return
    onCompare({
      start: locationPayload(start),
      finish: locationPayload(finish),
      options: { starting_tank: tank },
    })
  }

  function loadSample() {
    setStart(SAMPLE.start)
    setFinish(SAMPLE.finish)
  }

  return (
    <form className="form" onSubmit={submit}>
      <LocationInput
        id="start"
        label="Start"
        value={start}
        onChange={setStart}
        placeholder="e.g. Chicago, IL"
      />
      <LocationInput
        id="finish"
        label="Finish"
        value={finish}
        onChange={setFinish}
        placeholder="e.g. Houston, TX"
      />

      <StrategyPicker
        strategy={strategy}
        onStrategyChange={setStrategy}
        tank={tank}
        onTankChange={setTank}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <button
          type="submit"
          className="btn btn--primary btn--block"
          disabled={!canSubmit()}
        >
          {isLoading ? <><span className="spinner" /> Planning…</> : 'Plan this trip'}
        </button>
        <button
          type="button"
          className="btn btn--outline btn--block"
          onClick={compare}
          disabled={!canSubmit()}
          title="Run all three refuel strategies in parallel"
        >
          Compare strategies
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--block"
          onClick={loadSample}
          disabled={isLoading}
        >
          Try a sample trip
        </button>
      </div>
    </form>
  )
}
