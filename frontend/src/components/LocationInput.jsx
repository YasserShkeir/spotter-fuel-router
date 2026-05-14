import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { useDebounce } from '../hooks/useDebounce.js'

export default function LocationInput({ id, label, value, onChange, placeholder }) {
  const [text, setText] = useState(value?.label || '')
  const [suggestions, setSuggestions] = useState([])
  const [isOpen, setIsOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const debounced = useDebounce(text, 280)
  const containerRef = useRef(null)
  const skipNextSearch = useRef(false)

  // Sync external value -> input text (e.g. clear, sample button, etc.)
  useEffect(() => {
    if (value?.label !== text) setText(value?.label || '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value?.label])

  // Fetch suggestions when the debounced query changes (skipped right after
  // the user picks one, so we don't immediately re-search the selected text).
  useEffect(() => {
    if (skipNextSearch.current) {
      skipNextSearch.current = false
      return
    }
    if (!debounced || debounced.length < 3) {
      setSuggestions([])
      return
    }
    const controller = new AbortController()
    api
      .searchPlaces(debounced, { signal: controller.signal })
      .then((rows) => Array.isArray(rows) && setSuggestions(rows))
      .catch((err) => {
        if (err.name !== 'AbortError') setSuggestions([])
      })
    return () => controller.abort()
  }, [debounced])

  // Close on outside click.
  useEffect(() => {
    function onClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  function pick(s) {
    skipNextSearch.current = true
    setText(s.label)
    setSuggestions([])
    setIsOpen(false)
    onChange({ label: s.label, lat: s.lat, lon: s.lon })
  }

  function onInput(e) {
    const v = e.target.value
    setText(v)
    setIsOpen(true)
    setActiveIdx(0)
    // When the user edits, the previously-picked coords no longer match the
    // text — clear them so submit treats this as a query (not a trust-coords).
    onChange({ label: v })
  }

  function onKeyDown(e) {
    if (!isOpen || suggestions.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx((i) => (i + 1) % suggestions.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx((i) => (i - 1 + suggestions.length) % suggestions.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      pick(suggestions[activeIdx])
    } else if (e.key === 'Escape') {
      setIsOpen(false)
    }
  }

  return (
    <div className="field" ref={containerRef}>
      <label className="field__label" htmlFor={id}>{label}</label>
      <input
        id={id}
        className="input"
        type="text"
        value={text}
        onChange={onInput}
        onFocus={() => setIsOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        autoComplete="off"
      />
      {isOpen && suggestions.length > 0 ? (
        <div className="suggest" role="listbox">
          {suggestions.map((s, i) => (
            <div
              key={`${s.lat},${s.lon},${i}`}
              role="option"
              aria-selected={i === activeIdx}
              className={`suggest__item ${i === activeIdx ? 'suggest__item--active' : ''}`}
              onMouseDown={(e) => {
                e.preventDefault() // keep focus, prevent blur racing
                pick(s)
              }}
              onMouseEnter={() => setActiveIdx(i)}
            >
              {s.label}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
