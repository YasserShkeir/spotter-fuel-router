import { useEffect, useMemo } from 'react'
import L from 'leaflet'
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import { fmtGallons, fmtMiles, fmtUSD } from '../lib/format.js'

function pinIcon(kind, label) {
  return L.divIcon({
    html: `<div class="stop-marker stop-marker--${kind}">${label}</div>`,
    className: '',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })
}

function FitBounds({ coords }) {
  const map = useMap()
  useEffect(() => {
    if (!coords?.length) return
    const bounds = L.latLngBounds(coords)
    map.fitBounds(bounds, { padding: [40, 40] })
  }, [coords, map])
  return null
}

export default function RouteMap({ inputs, route, fuel }) {
  const latlngs = useMemo(
    () => (route?.geometry?.coordinates || []).map(([lon, lat]) => [lat, lon]),
    [route],
  )

  const startLatLon = inputs?.start ? [inputs.start.lat, inputs.start.lon] : null
  const finishLatLon = inputs?.finish ? [inputs.finish.lat, inputs.finish.lon] : null
  const bounds = useMemo(() => {
    if (!latlngs.length) return null
    return latlngs
  }, [latlngs])

  return (
    <div className="map">
      <MapContainer
        center={[39.5, -98]}
        zoom={4}
        scrollWheelZoom
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        />

        {latlngs.length ? (
          <>
            <Polyline positions={latlngs} pathOptions={{ color: '#ea580c', weight: 4, opacity: 0.85 }} />
            <FitBounds coords={bounds} />
          </>
        ) : null}

        {startLatLon ? (
          <Marker position={startLatLon} icon={pinIcon('origin', 'A')}>
            <Popup>
              <div className="popup">
                <div className="popup__title">Start</div>
                <div className="popup__sub">{inputs.start.label}</div>
              </div>
            </Popup>
          </Marker>
        ) : null}

        {finishLatLon ? (
          <Marker position={finishLatLon} icon={pinIcon('dropoff', 'B')}>
            <Popup>
              <div className="popup">
                <div className="popup__title">Finish</div>
                <div className="popup__sub">{inputs.finish.label}</div>
              </div>
            </Popup>
          </Marker>
        ) : null}

        {(fuel?.stops || []).map((s, i) => {
          const kind = s.kind === 'origin_fillup' ? 'fillup' : 'fuel'
          return (
            <Marker
              key={`${s.station.id}-${i}`}
              position={[s.station.lat, s.station.lon]}
              icon={pinIcon(kind, String(i + 1))}
            >
              <Popup>
                <div className="popup">
                  <div className="popup__title">{s.station.name}</div>
                  <div className="popup__sub">{s.station.city}, {s.station.state} · {s.station.address}</div>
                  <div className="popup__row">
                    <span>Price/gal</span>
                    <strong>{fmtUSD(s.price_per_gallon, { dp: 3 })}</strong>
                  </div>
                  <div className="popup__row">
                    <span>Bought</span>
                    <strong>{fmtGallons(s.gallons_purchased)}</strong>
                  </div>
                  <div className="popup__row">
                    <span>Cost</span>
                    <strong>{fmtUSD(s.cost_usd)}</strong>
                  </div>
                  <div className="popup__row">
                    <span>Mile</span>
                    <strong>{fmtMiles(s.miles_along)}</strong>
                  </div>
                </div>
              </Popup>
            </Marker>
          )
        })}
      </MapContainer>
    </div>
  )
}
