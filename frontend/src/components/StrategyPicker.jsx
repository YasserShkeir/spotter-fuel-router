import {
  STRATEGY_BLURBS,
  STRATEGY_LABELS,
  TANK_BLURBS,
  TANK_LABELS,
} from '../lib/format.js'

function RadioGroup({ label, value, onChange, options, blurbs }) {
  return (
    <div className="field">
      <span className="field__label">{label}</span>
      <div className="radio-group">
        {Object.entries(options).map(([key, optLabel]) => (
          <label
            key={key}
            className={`radio-option ${value === key ? 'radio-option--active' : ''}`}
          >
            <input
              type="radio"
              name={label}
              value={key}
              checked={value === key}
              onChange={() => onChange(key)}
              style={{ display: 'none' }}
            />
            <span className="radio-option__radio" />
            <span className="radio-option__body">
              <span className="radio-option__title">{optLabel}</span>
              {blurbs?.[key] ? <span className="radio-option__sub">{blurbs[key]}</span> : null}
            </span>
          </label>
        ))}
      </div>
    </div>
  )
}

export default function StrategyPicker({ strategy, onStrategyChange, tank, onTankChange }) {
  return (
    <>
      <RadioGroup
        label="Refuel strategy"
        value={strategy}
        onChange={onStrategyChange}
        options={STRATEGY_LABELS}
        blurbs={STRATEGY_BLURBS}
      />
      <RadioGroup
        label="Starting tank"
        value={tank}
        onChange={onTankChange}
        options={TANK_LABELS}
        blurbs={TANK_BLURBS}
      />
    </>
  )
}
