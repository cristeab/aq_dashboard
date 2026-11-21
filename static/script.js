// script.js - main page of the air quality dashboard

// Latest data received from the server
let currentData = {};
let currentNotifications = [];
const seenNotifications = new Set();

// Profiles (from api/profiles), by kind ("aqi", "co2", "noise", "comfort") and id
let profiles = { aqi: {}, co2: {}, noise: {}, comfort: {} };

// ---------------------------------------------------------------- translations

let translations = {};
let currentLanguage = localStorage.getItem('language') || 'en';

async function loadLanguage(lang) {
    if (!translations[lang]) {
        try {
            const response = await fetch(`static/translations_${lang}.json`);
            translations[lang] = await response.json();
        } catch (error) {
            console.error(`Failed to load translations for language ${lang}:`, error);
            translations[lang] = {};
        }
    }
}

async function initTranslations() {
    await loadLanguage('en'); // fallback
    if (currentLanguage !== 'en') {
        await loadLanguage(currentLanguage);
    }
}

function t(key) {
    const lang = currentLanguage || 'en';
    return (translations[lang] && translations[lang][key]) || (translations.en && translations.en[key]) || key;
}

/** Localized text of a profile ({en: ..., de: ...}), English as fallback. */
function tl(texts) {
    if (!texts) {
        return '';
    }
    return texts[currentLanguage] || texts.en || '';
}

function fillParams(text, params) {
    return Object.entries(params || {}).reduce((result, [key, value]) => result.split(`{${key}}`).join(value), text);
}

// ---------------------------------------------------------------- numbers and dates in the language of the page

/** Valid BCP 47 tag of a browser language, or null (some systems report POSIX locales like "en-US@posix"). */
function validLocale(tag) {
    if (!tag) {
        return null;
    }
    try {
        return Intl.getCanonicalLocales(tag.split('@')[0].split('.')[0].replace('_', '-'))[0] || null;
    } catch (error) {
        return null;
    }
}

/** BCP 47 locale of the page language (English: the regional variant of the browser, e.g. en-US dates). */
function pageLocale() {
    if (currentLanguage === 'en') {
        const browser = (navigator.languages || [navigator.language]).map(validLocale).find(l => l && l.startsWith('en'));
        return browser || 'en-GB';
    }
    return { ro: 'ro-RO', fr: 'fr-FR', de: 'de-DE' }[currentLanguage] || validLocale(currentLanguage) || 'en-GB';
}

const numberFormats = new Map();

/** Number with a fixed number of decimals, in the format of the page language. */
function fmtNumber(value, decimals = 0) {
    const key = `${pageLocale()}|${decimals}`;
    if (!numberFormats.has(key)) {
        numberFormats.set(key, new Intl.NumberFormat(pageLocale(), { minimumFractionDigits: decimals, maximumFractionDigits: decimals }));
    }
    const number = Number(value);
    // typographic minus instead of the hyphen-minus of some locales
    return (number < 0 ? '−' : '') + numberFormats.get(key).format(Math.abs(number));
}

/** Formats the numbers of a text from the server ("12.3", "−0.42", "500+", ">100") in the page language. */
function localizeNumberText(text) {
    return String(text).replace(/([−+-]?)(\d+(?:\.\d+)?)/g, (match, sign, digits) => {
        const decimals = digits.includes('.') ? digits.split('.')[1].length : 0;
        const formatted = fmtNumber(Number(digits), decimals);
        return (sign === '-' || sign === '−' ? '−' : sign) + formatted;
    });
}

/** Tick label of a gauge. */
function fmtTick(value) {
    return fmtNumber(value, Number.isInteger(value) ? 0 : 1);
}

function fmtDateTime(isoOrText) {
    const date = isoOrText ? new Date(isoOrText) : null;
    if (!date || Number.isNaN(date.getTime())) {
        return isoOrText || '';
    }
    const browserTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return new Intl.DateTimeFormat(pageLocale(), {
        dateStyle: 'short',
        timeStyle: 'medium',
        timeZone: browserTimeZone,
    }).format(date);
}

// ---------------------------------------------------------------- display options of this browser

/** Temperature unit: "C" or "F" (default: Fahrenheit only for the United States). */
function temperatureUnit() {
    const stored = localStorage.getItem('temperatureUnit');
    if (stored === 'C' || stored === 'F') {
        return stored;
    }
    return (validLocale(navigator.language) || '').toLowerCase() === 'en-us' ? 'F' : 'C';
}

/** Converts a temperature-like value ("°C" or "°F") to the selected unit. */
function convertTemperature(value, unit) {
    const target = temperatureUnit() === 'F' ? '°F' : '°C';
    if (unit === '°C' && target === '°F') {
        return { value: value * 9 / 5 + 32, unit: target };
    }
    if (unit === '°F' && target === '°C') {
        return { value: (value - 32) * 5 / 9, unit: target };
    }
    return { value, unit };
}

/** Colour palette: "cvd" (colour-blind safe, default) or "official" (colors of the standards). */
function palette() {
    return localStorage.getItem('palette') === 'official' ? 'official' : 'cvd';
}

/** Classes of the body for the colors of the icons (palette-cvd or palette-official). */
function applyPalette() {
    document.body.classList.toggle('palette-cvd', palette() === 'cvd');
    document.body.classList.toggle('palette-official', palette() === 'official');
}

function categoryColor(category) {
    return palette() === 'official' ? category.color : (category.cvd_color || category.color);
}

/** Text color that is readable on a background color (glyphs of the badges). */
function contrastingColor(hex) {
    const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
        .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.25 ? '#000000' : '#ffffff';
}

function showDustTiles() {
    return localStorage.getItem('showDustTiles') !== 'false';
}

function applyDustTilesVisibility() {
    document.getElementById('dust-tiles').classList.toggle('hidden', !showDustTiles());
}

// ---------------------------------------------------------------- categories

const POLLUTANT_LABELS = { pm25: 'PM2.5', pm10: 'PM10', o3: 'O₃', no2: 'NO₂', co: 'CO', co2: 'CO₂' };

function findCategory(categories, id) {
    return categories.find(c => c.id === id);
}

/**
 * Icon of a category, from its severity (position in the profile), so that the
 * category is not told by its color only: circle with a check mark (best),
 * circle with a dash, triangle, octagon (worst); a snowflake on the cold side
 * of the thermal comfort profiles.
 */
function severityIcon(categories, categoryId, neutralId) {
    const index = categories.findIndex(c => c.id === categoryId);
    const count = categories.length;
    let severity;
    if (neutralId) {
        const neutral = categories.findIndex(c => c.id === neutralId);
        if (index < neutral) {
            return 'sev-cold';
        }
        severity = (index - neutral) / Math.max(count - 1 - neutral, 1);
    } else {
        severity = index / Math.max(count - 1, 1);
    }
    if (severity <= 0) {
        return 'sev-ok';
    }
    return severity <= 0.34 ? 'sev-low' : severity <= 0.67 ? 'sev-mid' : 'sev-high';
}

/** Shows a category badge: icon shape + color, with a text for tooltips and screen readers. */
function setBadge(element, category, icon, label) {
    if (!element) {
        return;
    }
    if (!category) {
        element.hidden = true;
        element.removeAttribute('aria-label');
        element.removeAttribute('title');
        return;
    }
    const color = categoryColor(category);
    element.hidden = false;
    element.style.setProperty('--badge-color', color);
    element.style.setProperty('--badge-glyph', contrastingColor(color));
    element.innerHTML = `<svg class="icon badge-icon" aria-hidden="true"><use href="#${icon}"></use></svg>`;
    if (label) {
        element.setAttribute('aria-label', label);
        element.title = label;
    }
}

function averagingShortLabel(spec) {
    if (spec.type === 'nowcast') {
        return 'NowCast';
    }
    return spec.minutes !== undefined ? `${spec.minutes} min` : `${spec.hours} h`;
}

function averagingLabel(spec) {
    if (spec.type === 'nowcast') {
        return t('averaging_nowcast').replace('{hours}', spec.hours);
    }
    if (spec.type === 'leq') {
        return spec.minutes % 60 === 0 ? t('averaging_leq_hours').replace('{hours}', spec.minutes / 60)
            : t('averaging_leq_minutes').replace('{minutes}', spec.minutes);
    }
    if (spec.minutes !== undefined) {
        return t('averaging_minutes').replace('{minutes}', spec.minutes);
    }
    return t('averaging_hours').replace('{hours}', spec.hours);
}

/** Categories of a concentration profile with their upper limits (levels: [[id, upper]], e.g. from the engine). */
function concentrationCategories(profile, pollutant, levels) {
    const byId = Object.fromEntries(profile.categories.map(c => [c.id, c]));
    return (levels || profile.pollutants[pollutant].levels).map(([id, upper]) =>
        upper === null ? { ...byId[id], to: undefined } : { ...byId[id], to: upper });
}

function airIndexScale(profile, air) {
    if (profile.kind === 'concentration') {
        return { scale: profile.pollutants[air.pollutant].scale, categories: concentrationCategories(profile, air.pollutant, air.levels) };
    }
    return { scale: profile.scale, categories: profile.categories };
}

/** True if the last category only represents values above the index (e.g. CAQI "> 100", AQHI "10+"). */
function hasDisplayOnlyTopBand(profile) {
    const categories = profile.categories;
    if (profile.kind === 'additive_risk') {
        return true;
    }
    return categories.length > 1 && profile.above_scale_display === '>' + formatTick(categories[categories.length - 2].to);
}

// ---------------------------------------------------------------- air quality index gauge

let aqiGauge = null;
let comfortBarGauge = null;

/** Bands (with the colors of the palette), ticks and needle of the air quality gauge. */
function airIndexGauge(profile, air) {
    const { scale, categories } = airIndexScale(profile, air);
    let bands = profileBands(categories.map(c => ({ ...c, color: categoryColor(c) })), scale.min, scale.max);
    let ticks;
    let needle = air.value;
    if (profile.kind === 'banded') {
        // one band per level with the official colors (e.g. UK DAQI), labelled with the level number
        if (profile.level_colors && palette() === 'official') {
            bands = profile.level_colors.map((color, i) => ({ color, from: i, to: i + 1 }));
        }
        ticks = Array.from({ length: scale.max }, (_, i) => ({ value: i + 0.5, label: fmtNumber(i + 1) }));
        needle = air.value - 0.5;
    } else {
        let values;
        if (profile.kind === 'concentration') {
            values = [...innerBoundaries(bands), scale.max];
        } else {
            values = bands.map(band => band.to);
            if (hasDisplayOnlyTopBand(profile)) {
                values.pop();
            }
            if (air.above_scale) {
                needle = profile.kind === 'additive_risk' ? (profile.index_max + scale.max) / 2 : scale.max;
            }
        }
        ticks = values.map(v => ({ value: v, label: fmtTick(v) }));
    }
    return { bands, ticks, needle, scale, categories };
}

function updateAirIndex(air) {
    const profile = air ? profiles.aqi[air.profile] : undefined;
    const valueEl = document.getElementById('aqi-value');
    const unitEl = document.getElementById('aqi-unit');
    const labelEl = document.getElementById('aqi-label');
    const titleEl = document.getElementById('aqi-title');
    const canvas = document.getElementById('aqi-arc');
    ['pm25', 'pm10', 'no2', 'o3', 'co'].forEach(p => setBadge(document.getElementById(`dot-${p}`)));
    if (!profile) {
        aqiGauge.render({ bands: [], min: 0, max: 1, ticks: [], value: null });
        titleEl.textContent = '';
        valueEl.textContent = t('na');
        unitEl.textContent = '';
        labelEl.textContent = '';
        canvas.setAttribute('aria-label', t('no_index_data'));
        return;
    }
    const { bands, ticks, needle, scale, categories } = airIndexGauge(profile, air);
    aqiGauge.render({ bands, min: scale.min, max: scale.max, ticks, value: needle });

    const category = findCategory(categories, air.category);
    const title = profile.kind === 'concentration'
        ? `${POLLUTANT_LABELS[air.pollutant]} · ${averagingShortLabel(profile.pollutants[air.pollutant].averaging)}`
        : tl(profile.short_name);
    titleEl.textContent = title;
    valueEl.textContent = localizeNumberText(air.display);
    unitEl.textContent = profile.kind === 'concentration' ? ` ${air.unit}` : '';
    labelEl.textContent = category ? tl(category.name) : '';
    let description = t('gauge_aria').replace('{title}', title)
        .replace('{value}', valueEl.textContent + unitEl.textContent).replace('{category}', labelEl.textContent);
    if (air.dominant && air.dominant.length && profile.kind !== 'concentration') {
        description += ', ' + t('main_pollutant').replace('{pollutant}', air.dominant.map(p => POLLUTANT_LABELS[p]).join(', '));
    }
    if (air.provisional) {
        description += '. ' + t('provisional_note').replace('{coverage}', fmtNumber(air.coverage * 100));
    }
    canvas.setAttribute('aria-label', description);
    canvas.title = description;
    fitTextInCircle(document.querySelector('#aqi-gauge .aqi-value'), canvas, 70);

    // sub-index of each pollutant: badge next to its reading
    Object.entries(air.sub_indices || {}).forEach(([pollutant, sub]) => {
        const subCategories = profile.kind === 'concentration' ? concentrationCategories(profile, pollutant, sub.levels) : profile.categories;
        const subCategory = findCategory(subCategories, sub.category);
        if (!subCategory) {
            return;
        }
        let value = profile.kind === 'concentration' ? `${localizeNumberText(sub.display)} ${sub.unit}` : localizeNumberText(sub.display);
        if (profile.kind !== 'concentration') {
            value += ` (${fmtNumber(sub.concentration, Number.isInteger(sub.concentration) ? 0 : 1)} ${sub.unit})`;
        }
        let label = t('subindex_title')
            .replace('{profile}', profile.kind === 'concentration' ? POLLUTANT_LABELS[pollutant] : tl(profile.short_name))
            .replace('{value}', value + (sub.provisional ? '*' : ''))
            .replace('{category}', tl(subCategory.name))
            .replace('{averaging}', averagingLabel(sub.averaging));
        if (sub.corrected) {
            label += ` – ${t('pm25_corrected_note').replace('{correction}', t(`pm25_correction_${air.pm25_correction}`))}`;
        }
        setBadge(document.getElementById(`dot-${pollutant}`), subCategory, severityIcon(subCategories, sub.category), label);
    });
}

// ---------------------------------------------------------------- thermal comfort bar

function updateComfortIndex(comfort) {
    const display = document.getElementById('comfort-display');
    const profile = comfort ? profiles.comfort[comfort.profile] : undefined;
    if (!profile) {
        display.style.display = 'none';
        return;
    }
    display.style.display = '';
    const { min, max } = profile.scale;
    const bands = profileBands(profile.categories.map(c => ({ ...c, color: categoryColor(c) })), min, max);
    // positions in the unit of the profile, labels in the selected temperature unit
    const ticks = innerBoundaries(bands).map(v => ({ value: v, label: fmtTick(convertTemperature(v, profile.unit).value) }));
    comfortBarGauge.render({ bands, min, max, ticks, value: comfort.value });

    const category = findCategory(profile.categories, comfort.category);
    const converted = convertTemperature(comfort.value, comfort.unit);
    const value = converted.unit !== comfort.unit ? fmtNumber(converted.value, profile.decimals) : localizeNumberText(comfort.display);
    document.getElementById('comfort-title').textContent = tl(profile.short_name);
    const valueEl = document.getElementById('comfort-value');
    valueEl.textContent = value + (comfort.valid === false ? '*' : '');
    valueEl.title = comfort.valid === false ? t('comfort_out_of_range') : '';
    document.getElementById('comfort-unit').textContent = converted.unit ? ` ${converted.unit}` : '';
    const secondary = comfort.secondary;
    document.getElementById('comfort-secondary').textContent = secondary
        ? ` · ${t(`secondary_${secondary.id}`)} ${fmtNumber(secondary.value)} ${secondary.unit}` : '';
    document.getElementById('comfort-category-text').textContent = category ? tl(category.name) : '';
    setBadge(document.getElementById('comfort-badge'), category,
        severityIcon(profile.categories, comfort.category, profile.neutral_category));
    document.getElementById('comfort-bar').setAttribute('aria-label', t('gauge_aria')
        .replace('{title}', tl(profile.short_name))
        .replace('{value}', `${valueEl.textContent}${converted.unit ? ' ' + converted.unit : ''}`)
        .replace('{category}', category ? tl(category.name) : ''));
}

// ---------------------------------------------------------------- CO2 and noise readings with their classification

/** Value and badge of a reading classified by a profile (CO2, noise). */
function updateClassifiedReading(kind, result, valueId, badgeId, fallbackValue, fallbackUnit) {
    const valueEl = document.getElementById(valueId);
    const badge = document.getElementById(badgeId);
    const profile = result ? profiles[kind][result.profile] : undefined;
    if (!profile) {
        setBadge(badge);
        updateReading(valueId, fallbackValue, fallbackUnit, 0);
        return;
    }
    const categories = profile.kind === 'concentration'
        ? concentrationCategories(profile, 'co2', result.levels)
        : profile.categories;
    const category = findCategory(categories, result.category);
    updateReading(valueId, result.value, result.unit, profile.decimals ?? 0);
    if (result.provisional && kind !== 'noise') {
        valueEl.textContent += '*';
    }
    const averaging = kind === 'co2' ? profile.pollutants.co2.averaging : profile.averaging;
    let label = `${tl(profile.short_name)}: ${valueEl.textContent} · ${category ? tl(category.name) : ''} (${averagingLabel(averaging)})`;
    if (kind === 'noise' && fallbackValue !== undefined && fallbackValue !== null) {
        label += ` – ${t('noise_now').replace('{value}', fmtNumber(fallbackValue, 1))}`;
    }
    valueEl.title = label;
    setBadge(badge, category, severityIcon(categories, result.category), label);
}

// ---------------------------------------------------------------- readings

function updateReading(elementId, value, unit = '', decimals = 1) {
    const element = document.getElementById(elementId);
    const container = element.closest('.reading') || element.parentElement;
    if (value === undefined || value === null) {
        container.style.display = 'none';
        return;
    }
    container.style.display = '';
    element.textContent = fmtNumber(value, decimals) + (unit ? ` ${unit}` : '');
}

const SENSOR_NAMES = {
    bme688: 'BME688', scd41: 'SCD41', bmp390l: 'BMP390', sgp41: 'SGP41', zmod4510: 'ZMOD4510', ze07co: 'ZE07-CO',
    ltr390: 'LTR390', sound: 'ReSpeaker', airthings: 'Airthings', pmsa003: 'PMSA003',
};

/** Warning icon next to the readings of the sensors with a validation problem. */
function updateSensorFlags(status) {
    // flag on the tab of the sensors in the settings
    const states = Object.values(status || {});
    const tabFlag = document.getElementById('tab-sensors-flag');
    const worst = states.includes('alarm') ? 'alarm' : states.includes('warning') ? 'warning' : null;
    tabFlag.hidden = !worst;
    tabFlag.classList.toggle('alarm', worst === 'alarm');
    if (worst) {
        tabFlag.setAttribute('aria-label', t(`health_${worst}`));
    }
    document.querySelectorAll('.sensor-flag[data-flag]').forEach(flag => {
        const state = (status || {})[flag.dataset.flag];
        const visible = state === 'warning' || state === 'alarm';
        flag.hidden = !visible;
        flag.classList.toggle('alarm', state === 'alarm');
        if (visible) {
            const label = t(`sensor_flag_${state}`).replace('{sensor}', SENSOR_NAMES[flag.dataset.flag] || flag.dataset.flag);
            flag.setAttribute('aria-label', label);
            flag.title = label;
        }
    });
}

function updateDashboard(data) {
    currentData = data;
    document.getElementById('date-time').textContent = data.timestamp || (data.time ? fmtDateTime(data.time) : '');
    renderIndices();

    const pm = [['pm1.0', 'pm10'], ['pm2.5', 'pm25'], ['pm10', 'pm100']];
    const counts = [['pm0.3plus', 'pm03plus'], ['pm0.5plus', 'pm05plus'], ['pm1.0plus', 'pm10plus'],
        ['pm2.5plus', 'pm25plus'], ['pm5.0plus', 'pm50plus'], ['pm10plus', 'pm100plus']];
    [0, 1].forEach(i => {
        pm.forEach(([id, key]) => updateTile(`${id}_${i}`, data[`${key}_${i}`], 'µg/m³'));
        counts.forEach(([id, key]) => updateTile(`${id}_${i}`, data[`${key}_${i}`], ''));
    });

    const temperature = data.temperature === undefined || data.temperature === null ? null : convertTemperature(data.temperature, '°C');
    updateReading('temp-value', temperature ? temperature.value : null, temperature ? temperature.unit : '');
    updateReading('humidity-value', data.relative_humidity, '%');
    updateReading('pressure-value', data.pressure, 'hPa');
    updateClassifiedReading('noise', data.noise_index, 'noise-value', 'dot-noise', data.noise, 'dB');
    updateReading('visible-light-lux-value', data.visible_light_lux, 'lux');
    updateReading('uv-index-value', data.uv_index, '', 2);
    updateReading('no2-value', data.no2, 'ppb');
    updateReading('o3-value', data.o3, 'ppb');
    updateReading('co-value', data.co, 'ppm');
    updateReading('voc-value', data.voc, '', 0);
    updateReading('nox-value', data.nox, '', 0);
    updateClassifiedReading('co2', data.co2_index, 'co2-value', 'dot-co2', data.co2, 'ppm');
    updateReading('radon-value', data.radon_week_avg, 'Bq/m³', 0);
    updateSensorFlags(data.sensor_status);
}

function updateTile(elementId, value, unit) {
    const element = document.getElementById(elementId);
    if (value === undefined || value === null) {
        element.parentElement.style.display = 'none';
        return;
    }
    element.parentElement.style.display = '';
    element.textContent = fmtNumber(value, 0) + (unit ? ` ${unit}` : '');
}

/** Redraws the indices, e.g. after a theme, language or display option change. */
function renderIndices() {
    updateAirIndex(currentData.air_index);
    updateComfortIndex(currentData.comfort_index);
}

function rerender() {
    updateDashboard(currentData);
    updateNotifications(currentNotifications);
}

// ---------------------------------------------------------------- server requests

/** fetch() of the API; goes to the login page when the session has ended. */
async function api(path, options = {}) {
    const response = await fetch(path, options);
    if (response.status === 401 || response.status === 403) {
        const detail = response.status === 403 ? (await response.clone().json().catch(() => ({}))).detail : null;
        // not logged in, or the default password must be changed first (on the login page)
        if (response.status === 401 || detail === 'password_change_required') {
            globalThis.location.href = 'login';
            throw new Error(t('login_required'));
        }
    }
    return response;
}

async function loadProfiles() {
    try {
        const response = await api('api/profiles');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        profiles = Object.fromEntries(Object.entries(data).map(([kind, list]) => [kind, Object.fromEntries(list.map(p => [p.id, p]))]));
    } catch (error) {
        console.error('Failed to load the index profiles:', error);
    }
}

// ---------------------------------------------------------------- notifications

function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

/** Key of a notification for the "seen" state; maintenance alarms keep their key
 * while their figures (e.g. the number of hours) are updated. */
function notificationKey(n) {
    return n.type === 'maintenance' ? `${n.parameter}-${n.timestamp}` : `${n.parameter}-${n.timestamp}-${n.message}`;
}

/** Parameters of a maintenance alarm for its localized text. */
function localizedParams(params) {
    const result = {};
    Object.entries(params || {}).forEach(([key, value]) => {
        if (key === 'sensor' && SENSOR_NAMES[value]) {
            result[key] = SENSOR_NAMES[value];
        } else if (key === 'other' && SENSOR_NAMES[value]) {
            result[key] = SENSOR_NAMES[value];
        } else if (key === 'quantity') {
            result[key] = t(`quantity_${value}`);
        } else if (key === 'since') {
            result[key] = new Intl.DateTimeFormat(pageLocale(), { dateStyle: 'medium' }).format(new Date(`${value}T00:00:00`));
        } else if (typeof value === 'number') {
            result[key] = fmtNumber(value, Number.isInteger(value) ? 0 : 1);
        } else {
            result[key] = value;
        }
    });
    return result;
}

const NOTIFICATION_PROFILE_KINDS = { aqi: 'aqi', comfort_index: 'comfort', co2: 'co2', noise: 'noise' };

function notificationTexts(n) {
    let param = t(`param_${n.parameter}`);
    if (param === `param_${n.parameter}`) {
        param = n.parameter.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }
    const kind = NOTIFICATION_PROFILE_KINDS[n.parameter];
    const profile = n.profile && kind ? profiles[kind][n.profile] : undefined;
    if (profile) {
        param = tl(profile.short_name);
    }
    let message = n.message;
    let recommendation = '';
    const category = profile ? findCategory(profile.categories, n.interval_name) : undefined;
    if (category) {
        // alerts of the engines: category of the profile and its recommendation
        const converted = convertTemperature(Number(n.value), n.unit);
        const value = converted.unit !== n.unit ? fmtNumber(converted.value, 1) : localizeNumberText(n.display);
        message = t('notification_data_alert')
            .replace('{value}', value)
            .replace(' {unit}', converted.unit ? ` ${converted.unit}` : '')
            .replace('{interval_name}', tl(category.name))
            .replace('{interval_desc}', tl(category.description));
        recommendation = tl(category.recommendation);
    } else if (n.type === 'maintenance') {
        const group = n.parameter.split(':')[0];
        param = t(`param_${group}`);
        const prefix = group === 'sensors' ? 'validation' : 'maintenance';
        message = fillParams(t(`${prefix}_${n.code}`), localizedParams(n.params));
        recommendation = fillParams(t(`${prefix}_${n.code}_action`), localizedParams(n.params));
    } else if (n.type === 'missing_data') {
        message = t('notification_missing_data').replace('{parameter}', param);
    } else if (n.type === 'data_alert') {
        // Some interval names contain spaces ("very quiet"), translation keys use underscores
        const intervalId = String(n.interval_name).replace(/ /g, '_');
        let interval = t(`interval_${intervalId}`);
        if (interval === `interval_${intervalId}`) {
            interval = n.interval_name;
        }
        let description = t(`desc_${n.parameter}_${intervalId}`);
        if (description === `desc_${n.parameter}_${intervalId}`) {
            const fallback = `desc_radon_1day_avg_${intervalId}`;
            description = n.parameter.startsWith('radon') && t(fallback) !== fallback ? t(fallback) : (n.interval_description || '');
        }
        const converted = convertTemperature(Number(n.value), n.unit);
        message = t('notification_data_alert')
            .replace('{value}', fmtNumber(converted.value, 1))
            .replace('{unit}', converted.unit || '')
            .replace('{interval_name}', interval)
            .replace('{interval_desc}', description);
    }
    return { param, message, recommendation };
}

function updateNotifications(notifications) {
    const list = document.getElementById('notifications-list');
    if (!list) {
        return;
    }
    currentNotifications = notifications || [];
    list.innerHTML = '';
    const dot = document.getElementById('notification-dot');
    if (currentNotifications.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'notification-item';
        empty.textContent = t('no_notifications');
        list.appendChild(empty);
        dot.classList.add('hidden');
        return;
    }
    currentNotifications.forEach(n => {
        const { param, message, recommendation } = notificationTexts(n);
        const item = document.createElement('div');
        item.className = 'notification-item' + (n.type === 'maintenance' ? ' maintenance' : '');
        item.innerHTML = `
            <div class="notification-head">
                <span class="notification-param">${n.type === 'maintenance' ? '<svg class="icon" aria-hidden="true"><use href="#i-flag"></use></svg>' : ''}${escapeHtml(param)}</span>
                <time class="notification-time" ${n.time ? `datetime="${escapeHtml(n.time)}"` : ''}>${escapeHtml(n.time ? fmtDateTime(n.time) : n.timestamp)}</time>
            </div>
            <div class="notification-message">${escapeHtml(message)}</div>
            ${recommendation ? `<div class="notification-recommendation">${escapeHtml(recommendation)}</div>` : ''}`;
        list.appendChild(item);
    });
    const unseen = currentNotifications.some(n => !seenNotifications.has(notificationKey(n)));
    dot.classList.toggle('hidden', !unseen);
    document.getElementById('notifications-btn').setAttribute('aria-label',
        t('notifications_title') + (unseen ? ` (${t('notifications_unseen')})` : ''));
}

// ---------------------------------------------------------------- page

function translatePage() {
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.getAttribute('data-i18n')); });
    document.querySelectorAll('[data-i18n-title]').forEach(el => el.setAttribute('title', t(el.getAttribute('data-i18n-title'))));
    document.querySelectorAll('[data-i18n-aria]').forEach(el => el.setAttribute('aria-label', t(el.getAttribute('data-i18n-aria'))));
    document.title = t('title');
}

document.addEventListener('DOMContentLoaded', async function () {
    await initTranslations();

    const header = document.querySelector('.header');
    const tilesMatrix = document.getElementById('dust-tiles');
    const alignHeaderRule = () => {
        const width = tilesMatrix.getBoundingClientRect().width;
        if (width > 0) {
            header.style.setProperty('--tiles-matrix-width', `${width}px`);
            const rightInset = Math.max(0, (header.getBoundingClientRect().width - width) / 2);
            header.style.setProperty('--tiles-matrix-right-inset', `${rightInset}px`);
        }
    };
    alignHeaderRule();
    if (globalThis.ResizeObserver) {
        new ResizeObserver(alignHeaderRule).observe(tilesMatrix);
    } else {
        globalThis.addEventListener('resize', alignHeaderRule);
    }

    function setTheme(theme) {
        document.body.classList.toggle('dark-theme', theme === 'dark');
        localStorage.setItem('theme', theme);
        if (aqiGauge) {
            renderIndices(); // the tick mark and outlines follow the theme colors
        }
    }

    const languageMenu = initLanguageMenu(document.querySelector('#panel-display .language-container'), lang => updateLanguage(lang));

    async function updateLanguage(lang) {
        await loadLanguage(lang);
        currentLanguage = lang;
        localStorage.setItem('language', lang);
        document.documentElement.lang = lang;
        translatePage();
        languageMenu.setActive(lang);
        if (aqiGauge) {
            rerender();
        }
        if (document.getElementById('settings-dialog').open) {
            buildSettingsSections();
        }
    }

    applyPalette();
    const savedTheme = localStorage.getItem('theme');
    setTheme(savedTheme || (globalThis.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
    await updateLanguage(currentLanguage);
    document.getElementById('theme-toggle-btn').addEventListener('click', () =>
        setTheme(document.body.classList.contains('dark-theme') ? 'light' : 'dark'));

    aqiGauge = new ArcGauge(document.getElementById('aqi-gauge'), { size: 240, radius: 80, lineWidth: 15, labelOffset: 20, minLabelAngle: 0.22 });
    comfortBarGauge = new BarGauge(document.getElementById('comfort-bar'));
    applyDustTilesVisibility();
    await loadProfiles();
    updateDashboard({});
    initSettings();

    document.getElementById('logout-btn').addEventListener('click', async () => {
        try {
            await fetch('api/logout', { method: 'POST' });
        } finally {
            globalThis.location.href = 'login';
        }
    });

    // WebSocket with automatic reconnection; code 4401: not logged in
    function connectWebSocket() {
        const protocol = globalThis.location.protocol === 'https:' ? 'wss:' : 'ws:';
        let path = globalThis.location.pathname;
        if (!path.endsWith('/')) {
            path = path.slice(0, path.lastIndexOf('/') + 1);
        }
        const socket = new WebSocket(`${protocol}//${globalThis.location.host}${path}ws`);
        socket.onmessage = event => {
            const data = JSON.parse(event.data);
            if (data.type === 'data') {
                updateDashboard(data.payload);
            } else if (data.type === 'notification') {
                updateNotifications(data.payload);
            }
        };
        socket.onclose = event => {
            if (event.code === 4401) {
                globalThis.location.href = 'login';
                return;
            }
            console.warn('WebSocket disconnected. Reconnecting in 5 seconds...');
            setTimeout(connectWebSocket, 5000);
        };
        socket.onerror = () => socket.close();
    }
    connectWebSocket();

    // Notifications dropdown
    const notificationsBtn = document.getElementById('notifications-btn');
    const notificationsList = document.getElementById('notifications-list');

    function setNotificationsOpen(open) {
        notificationsList.classList.toggle('hidden', !open);
        notificationsBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    notificationsBtn.addEventListener('click', event => {
        setNotificationsOpen(notificationsList.classList.contains('hidden'));
        languageMenu.close();
        currentNotifications.forEach(n => seenNotifications.add(notificationKey(n)));
        document.getElementById('notification-dot').classList.add('hidden');
        event.stopPropagation();
    });
    document.getElementById('language-btn').addEventListener('click', () => setNotificationsOpen(false));
    document.addEventListener('click', event => {
        if (!notificationsBtn.contains(event.target) && !notificationsList.contains(event.target)) {
            setNotificationsOpen(false);
        }
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            setNotificationsOpen(false);
        }
    });
    updateNotifications([]);
});
