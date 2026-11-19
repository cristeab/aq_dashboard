# Index Profiles

The air quality index (`aqi/`), the indoor CO₂ classification (`co2/`), the noise (`noise/`) and the thermal comfort
index (`comfort/`) are computed by configurable engines (`aqi_engine.py`, `noise_engine.py`, `comfort_engine.py`) from the
profiles of this directory. The profiles used by all screens and by the notifications are selected in the web interface
(settings button) and stored in the database; "Restore the defaults" selects the recommended ones (US EPA AQI,
EN 16798-1, WHO indoor noise, ISO 7730 PMV/PPD).

| Profile | File | Kind | Summary |
|---|---|---|---|
| US EPA AQI | `aqi/us_epa.json` | index | 0–500, 2024 PM2.5 breakpoints, NowCast (12 h) for particles, 8 h O₃/CO, 1 h NO₂ |
| US EPA – fast | `aqi/us_epa_fast.json` | index | EPA breakpoints applied to 10-minute means (indicative, like the former "10-min. AQI") |
| EEA European AQI | `aqi/eea_eaqi.json` | banded | 6 levels (good … extremely poor), 2024 thresholds, 24 h PM, 1 h NO₂/O₃, µg/m³ at 20 °C |
| European CAQI | `aqi/eu_caqi.json` | index | CiteAir hourly grid, 0–100 (> 100 = "very high"), µg/m³ at 20 °C (older European index) |
| UK DAQI | `aqi/uk_daqi.json` | banded | 10 levels in 4 bands (COMEAP), 24 h PM, 8 h O₃, 1 h NO₂ |
| China AQI | `aqi/china_mee.json` | index | HJ 633-2012 real-time report, 24 h PM, 1 h NO₂/CO, 1 h and 8 h O₃, sub-indices rounded up |
| India NAQI | `aqi/india_naqi.json` | index | CPCB 0–500, 24 h PM/NO₂, 8 h O₃/CO, needs 3 pollutants incl. PM; "severe" upper limits extrapolated |
| Korea CAI | `aqi/korea_cai.json` | index | AirKorea 0–500, 24 h PM, 1 h gases in ppm, +50/+75 when 2/3+ pollutants are "unhealthy" |
| Canada AQHI | `aqi/canada_aqhi.json` | additive_risk | 1–10+, sum of the risks of NO₂, O₃ and PM2.5 (3 h means) |
| Raw concentration | `aqi/raw_who.json` | concentration | 10-minute mean of a selectable pollutant compared with the WHO 2021 guideline levels |
| CO₂ – EN 16798-1 | `co2/co2_en16798.json` | concentration | indoor ventilation categories I–IV, CO₂ above a selectable outdoor level (left column) |
| CO₂ – UBA | `co2/co2_uba.json` | concentration | German Environment Agency: < 1000 / 1000–2000 / > 2000 ppm (left column) |
| Noise – WHO indoor | `noise/who_1999_indoor.json` | noise | LAeq 1 h vs the WHO 1999 indoor guidelines of the room (bedroom: 35 dB(A) day, 30 dB(A) night) |
| Noise – EU occupational | `noise/eu_2003_10_occupational.json` | noise | LAeq 8 h vs the action values 80 / 85 / 87 dB(A) of Directive 2003/10/EC |
| Noise – NIOSH | `noise/niosh_rel.json` | noise | LAeq 8 h vs the NIOSH REL 85 dB(A) (action level 82 dB(A), 3 dB exchange rate) |
| Thom DI – Giles | `comfort/thom_giles.json` | | Thom discomfort index (°C), classes of Giles et al. (1990) |
| Thom DI – Kyle | `comfort/thom_kyle.json` | | Thom discomfort index (°C), 10 bioclimatic classes of Kyle (1994), incl. cold |
| Thom THI (1959) | `comfort/thom_thi_1959.json` | | Thom's original temperature-humidity index in °F (70 / 75 / 79) |
| Humidex | `comfort/humidex.json` | | Environment Canada humidex |
| NWS heat index | `comfort/nws_heat_index.json` | | US NWS heat index in °C, categories of the current NWS chart |
| PMV/PPD | `comfort/iso7730_pmv.json` | | ISO 7730 office comfort, categories A/B/C, options: clothing, activity, air speed |

The PM2.5 concentrations can be corrected for humidity before any averaging (settings, dust sensors section):
Barkjohn et al. (2021), its extension for smoke (US EPA 2022) or none (see `pm_correction.py`).

Profiles are validated when the web server starts: an invalid file is skipped and the reason is written to the systemd journal. View it with `sudo journalctl -u aq_dashboard.service`. Run `pytest tests/test_profiles.py` after editing a profile.

## Common Fields

| Field | Description |
|---|---|
| `id` | identifier, must match the file name |
| `order` | position in the settings list (optional) |
| `extends` | id of a profile whose fields are inherited; the fields of this file replace them (optional) |
| `name`, `short_name`, `description` | texts, e.g. `{"en": "...", "ro": "...", "fr": "...", "de": "..."}`; `en` is mandatory and is the fallback |
| `reference` | source of the breakpoints/formula |
| `upper_bound` | `inclusive` (value ≤ limit belongs to the category, usual for indices) or `exclusive` (value < limit) |
| `categories` | ordered list of `{id, to, color, cvd_color, name, description, recommendation}`; `to` is the upper limit, `color` the official color, `cvd_color` the color of the colour-blind safe palette (Okabe–Ito, default of the web interface) |
| `options` | optional list of `{id, values, default, label, value_labels?, unit?}` selected in the settings (values are strings; numeric options may have "auto" values computed by the engine, e.g. the clothing of the season) |

## Air Quality Index Profiles (`kind: "index"`)

| Field | Description |
|---|---|
| `index_rounding` | `nearest`, `ceil` (China) or `floor` |
| `gas_reference_temperature_c` | temperature for the ppb ↔ µg/m³ conversion (EU 20 °C, US/China/WHO 25 °C) |
| `dominant_pollutant_min_index` | the main pollutant is only reported above this index (China: 50) |
| `scale` | `{min, max}` of the gauge; the last category must end at `max` |
| `above_scale_display` | text shown when a concentration is above the highest breakpoint, e.g. `500+`, `>100` |
| `pollutants` | `{pm25, pm10, o3, no2, co}` → list of breakpoint tables; the sub-index of a pollutant is the highest of its tables, the index is the highest sub-index |

Breakpoint table:

| Field | Description |
|---|---|
| `averaging` | `{"type": "mean", "hours": 1..24}`, `{"type": "mean", "minutes": 1..60}` or `{"type": "nowcast", "hours": 3..24, "min_weight": 0.5}` |
| `unit` | `ug/m3`, `mg/m3`, `ppb` or `ppm` (particles: `ug/m3` only) |
| `decimals`, `rounding` | the average is rounded (`round`) or truncated (`truncate`, US EPA) before the lookup |
| `breakpoints` | `[[C_low, C_high, I_low, I_high], ...]`; gaps between segments (e.g. 9.0 / 9.1) are allowed |
| `below_range` | `clamp` (default) or `not_applicable` (e.g. EPA 1-hour ozone below 0.125 ppm) |
| `above_range` | `cap` (default: highest index, shown with `above_scale_display`) or `not_applicable` |
| `note` | optional explanation shown in the settings |

Averages use the rolling hours (or minutes) ending now. As in the US EPA and EU rules, an hour is valid with data for
at least 45 minutes and an N-hour mean needs 75 % valid hours (the NowCast: 2 of the last 3 hours). With less data
(e.g. after a restart) the available data is used and the index is shown as provisional (`*`).

Optional rules: `requirements` (`{"min_pollutants": 3, "one_of": ["pm25", "pm10"]}`, India) and
`multi_pollutant_bonus` (`{"from_category": "unhealthy", "bonus": [[2, 50], [3, 75]]}`, Korea).

## Banded Profiles (`kind: "banded"`)

Each pollutant table has `thresholds` (upper limit of each level, e.g. 9 limits for 10 levels) instead of `breakpoints`; the
index is the highest level. The `scale` goes from 0 to the number of levels, the `to` of the categories are levels
(e.g. UK DAQI: low to 3, moderate to 6...). `level_colors` optionally gives one color per level for the gauge.

## Additive Risk Profiles (`kind: "additive_risk"`)

Canada AQHI: index = `scale_factor` × Σ(exp(`beta` × C) − 1) over the `terms` (one per pollutant, with `averaging`,
`unit`, `decimals`, `rounding`, `beta`), rounded (`index_rounding`), at least `index_min`; values above `index_max` are
shown with `above_scale_display` (e.g. `10+`).

## Concentration Profiles (`kind: "concentration"`)

The gauge shows the averaged concentration of the pollutant selected with the `pollutant` option (not needed for a
single pollutant). Each pollutant defines `averaging`, `unit`, `decimals`, `rounding`, the gauge `scale` and `levels`:
`[[category id, upper limit], ..., [category id, null]]`. With `levels_offset_option`, the value of a numeric option is
added to the limits (EN 16798-1: CO₂ above the outdoor level).

## Indoor CO₂ Profiles (`co2/`)

Concentration profiles (see above) of the single pollutant `co2`; they classify the CO₂ reading of the left column and
do not replace the air quality index.

## Noise Profiles (`noise/`)

| Field | Description |
|---|---|
| `averaging` | `{"type": "leq", "minutes": N}`: equivalent continuous sound level (energy average) of the last N minutes |
| `unit`, `decimals`, `scale` | display unit (dB(A)), rounding and range |
| `levels` | `[[category id, upper limit], ..., [category id, null]]`, absolute or, with `limits`, relative to the guideline limit |
| `limits` | optional `{"option": <option id>, "values": {<option value>: [{id: day/evening/night, from: "HH:MM", to: "HH:MM", limit}]}}`: guideline limit by option value (e.g. the room) and time of the day (local time) |

## Thermal Comfort Profiles

| Field | Description |
|---|---|
| `formula` | `thom_di` (°C), `thom_thi_f` (°F), `humidex`, `heat_index_c` or `pmv_iso7730` (needs the options `clo`, `met`, `air_speed`), computed from the temperature and relative humidity of the BME688 |
| `unit`, `decimals`, `signed` | display unit and rounding (with `signed`, positive values get a `+`); the category is determined from the rounded value |
| `scale` | `{min, max}` of the gauge (values outside are shown at the end of the gauge) |
| `categories` | the last category has no `to` (open ended) |
| `neutral_category` | id of the category of thermal neutrality: the categories before it are on the cold side (snowflake icon) |

New formulas are added to `FORMULAS` in `comfort_engine.py` and to `COMFORT_FORMULAS` in `profile_loader.py`.
