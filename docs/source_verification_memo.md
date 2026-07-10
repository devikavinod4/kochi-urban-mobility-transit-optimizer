# Source Verification Memo

**Project:** Kochi Urban Mobility & Transit Optimizer
**Deliverable:** D0.2 — Source Verification (Phase 0)
**Status:** Living document — updated as sources are verified
**Last updated:** 2026-07-10

---

## Purpose

Before building ingestion pipelines, each external data source is checked to
confirm it is (a) reachable, (b) returning the data the project assumes, and
(c) usable within free-tier limits. This memo records what has been verified,
what remains outstanding, and the chosen fallback for each source.

Data availability changes over time, so each entry is dated. Sources marked
"Not yet checked" are planned but unconfirmed — they must not be treated as
available until verified.

---

## Summary

| Source | Data | Status | Access | Cost / limit | Fallback |
|---|---|---|---|---|---|
| TomTom Routing API | Traffic / travel times | ✅ Verified (2026-07-10) | REST, API key | Free: 2,500 non-tile req/day | Google Distance Matrix / HERE |
| Open-Meteo | Weather / rainfall | ✅ Verified (2026-07-10) | REST, no key | Free, no key | IMD gridded / Visual Crossing |
| KMRL metro schedule | Metro network / timetable | ⚠️ Not yet checked | GTFS / scrape | TBD | Manual GTFS-lite from timetables |
| Kochi Water Metro | Water metro routes | ⚠️ Not yet checked | Scrape / manual | TBD | Manual compilation |
| KMRL ridership | Metro ridership | ⚠️ Not yet checked | Press / RTI / news | TBD | Daily figures from media |
| OpenStreetMap | Road network / POIs | ⚠️ Not yet checked | OSMnx / Overpass | Free | Geofabrik Kerala extract |
| Bus routes (KSRTC/private) | Bus routes | ⚠️ Not yet checked | Overpass / GTFS | TBD | Digitize key feeder routes manually |

Legend: ✅ verified live · ⚠️ planned, not yet confirmed · ❌ confirmed unavailable

---

## Verified sources

### TomTom Routing API (traffic)

- **Endpoint tested:** `calculateRoute` on a single Kochi route (Kaloor → Vyttila).
- **Result:** HTTP 200; response contained `routes[0].summary` with
  `travelTimeInSeconds`, `lengthInMeters`, and `trafficDelayInSeconds`.
- **Key field:** `travelTimeInSeconds` — the core signal for all congestion analysis.
- **Auth:** API key (Evaluation / free billing), stored in `.env`, passed via
  request params (never in the URL string or committed to Git).
- **Verified by:** `ingestion/verify_sources.py` — authenticated call, live pass.

### Open-Meteo (weather)

- **Endpoint tested:** `/v1/forecast` for Kochi city-centre coordinates,
  requesting `temperature_2m`, `precipitation`, `rain`.
- **Result:** HTTP 200; `current` object returned temperature and precipitation,
  with a `current_units` object confirming units (°C, mm).
- **Key fields:** `precipitation`, `rain` (mm) — the rainfall signal for the
  weather-impact analysis.
- **Auth:** none required.
- **Verified by:** `ingestion/verify_sources.py` — live pass.

---

## Key findings

### 1. Timezone mismatch between sources (must normalize in Phase 2)

TomTom returns timestamps in **IST** (e.g. `2026-07-08T01:53:55+05:30`).
Open-Meteo returned **GMT** (`utc_offset_seconds: 0`, `timezone: "GMT"`).

If traffic and weather were joined on timestamp without normalization, every
rainfall reading would align against traffic from ~5.5 hours away — silently
corrupting the rainfall-vs-travel-time analysis with no error raised.

**Resolution (Phase 2):** normalize all timestamps to IST. Two options —
(a) pass `&timezone=Asia/Kolkata` so Open-Meteo returns IST directly, or
(b) store everything in UTC and convert at the analysis layer (more robust for
multi-source joins). Decision deferred to Phase 2 per SOW.

### 2. TomTom exposes traffic delay separately

The response includes `trafficDelayInSeconds` — the portion of travel time
attributable to traffic vs. free-flow. This is a richer signal than raw travel
time and should help separate rain effects from rush-hour effects in the
Phase 3 regression.

### 3. Free-tier budget is comfortable

TomTom free tier allows 2,500 non-tile requests/day. Planned polling of ~10
origin-destination pairs every 30 minutes = ~480 calls/day (~960/day at 15-min
intervals) — well within limits. Open-Meteo has no key or documented cap for
this usage. Projected data-acquisition cost: **₹0**.

---

## Outstanding / at-risk sources

- **Transit (KMRL metro, Water Metro):** highest-risk gap. Public GTFS may not
  exist in clean form; likely requires building GTFS-lite from published
  timetables. **Next step:** confirm what KMRL actually publishes before D0.3.
- **Ridership:** likely only monthly granularity; supplement with media-reported
  daily figures. Analysis may be reframed at monthly grain.
- **OpenStreetMap:** expected reliable via OSMnx/Overpass; not yet loaded.
  Verification deferred to Phase 1 (road-network load into PostGIS).

---

## Next steps

1. Investigate transit-source availability (KMRL / Water Metro) — the true
   remaining unknown in Phase 0.
2. Finalize OD-pair and corridor list (D0.3).
3. Install PostgreSQL 16 + PostGIS locally.
4. Update this memo as each outstanding source is checked.
