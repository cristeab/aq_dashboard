// settings.js - settings dialog: profiles and sensors (device-wide), display options (this browser), account

let deviceSettings = null;

const PROFILE_SECTIONS = [
    { kind: 'aqi', container: 'settings-aqi', title: 'settings_aqi_section' },
    { kind: 'co2', container: 'settings-co2', title: 'settings_co2_section' },
    { kind: 'noise', container: 'settings-noise', title: 'settings_noise_section' },
    { kind: 'comfort', container: 'settings-comfort', title: 'settings_comfort_section' },
    { kind: 'uv', container: 'settings-uv', title: 'settings_uv_section' },
    { kind: 'voc', container: 'settings-voc', title: 'settings_voc_section' },
];

/** Number in the format of the page language; without decimals: as many as the value has (e.g. a
 * coefficient 0.000871), at most 6. */
function formatNumber(value, decimals) {
    if (decimals === undefined) {
        const text = String(Math.abs(value));
        decimals = text.includes('.') ? Math.min(6, text.split('.')[1].length) : 0;
    }
    return fmtNumber(value, decimals);
}

function element(tag, attributes = {}, ...children) {
    const el = document.createElement(tag);
    Object.entries(attributes).forEach(([key, value]) => {
        if (key === 'className') {
            el.className = value;
        } else {
            el.setAttribute(key, value);
        }
    });
    children.forEach(child => el.append(child instanceof Node ? child : document.createTextNode(child)));
    return el;
}

/** Value range of each category, as shown in the legend. */
function categoryRanges(categories, upperBound, integerIndex, displayOnlyTop, decimals, convert = v => v) {
    const format = value => formatNumber(convert(value), decimals);
    let previous = null;
    return categories.map((category, i) => {
        let range;
        const isLast = i === categories.length - 1;
        if (isLast && (category.to === undefined || displayOnlyTop)) {
            range = upperBound === 'inclusive' ? `> ${format(previous)}` : `≥ ${format(previous)}`;
        } else if (previous === null) {
            range = upperBound === 'inclusive' ? `≤ ${format(category.to)}` : `< ${format(category.to)}`;
            if (integerIndex) {
                range = `${format(0)} –\u00a0${format(category.to)}`;
            }
        } else {
            const from = integerIndex ? previous + 1 : previous;
            range = `${format(from)} –\u00a0${format(category.to)}`;
        }
        previous = category.to;
        return range;
    });
}

/** Legend: badge (color and icon of the category), name, range, recommendation. */
function legendTable(categories, ranges, neutralId) {
    const table = element('table', { className: 'settings-table legend' },
        element('thead', {}, element('tr', {},
            element('th', {}, t('col_category')), element('th', {}, t('col_range')), element('th', {}, t('col_recommendation')))));
    const body = element('tbody');
    categories.forEach((category, i) => {
        const badge = element('span', { className: 'cat-badge', 'aria-hidden': 'true' });
        setBadge(badge, category, severityIcon(categories, category.id, neutralId));
        badge.removeAttribute('title');
        body.append(element('tr', {},
            element('td', {}, badge, element('span', { className: 'legend-name', title: tl(category.description) }, tl(category.name))),
            element('td', { className: 'range' }, ranges[i]),
            element('td', {}, tl(category.recommendation))));
    });
    table.append(body);
    return table;
}

function unitLabel(unit) {
    return { 'ug/m3': 'µg/m³', 'mg/m3': 'mg/m³' }[unit] || unit;
}

function selectedOptions(kind, profile) {
    return ((deviceSettings || {})[`${kind}_profile_options`] || {})[profile.id] || {};
}

function optionValue(kind, profile, optionId) {
    const option = profile.options.find(o => o.id === optionId);
    return selectedOptions(kind, profile)[optionId] || option.default;
}

/** Levels of a concentration profile with the offsets of its options applied (as the engine). */
function effectiveLevels(profile, pollutant, options) {
    const spec = profile.pollutants[pollutant];
    let offset = 0;
    if (spec.levels_offset_option) {
        const option = profile.options.find(o => o.id === spec.levels_offset_option);
        offset = Number(options[option.id] || option.default);
    }
    return spec.levels.map(([id, upper]) => [id, upper === null ? null : upper + offset]);
}

function tableOf(headers, rows) {
    return element('table', { className: 'settings-table' },
        element('thead', {}, element('tr', {}, ...headers.map(h => element('th', {}, h)))),
        element('tbody', {}, ...rows.map(cells => element('tr', {}, ...cells.map(c => element('td', { className: 'nowrap' }, c))))));
}

/** Threshold tables of a banded profile (level -> concentration range). */
function thresholdTables(profile) {
    const container = element('div', { className: 'breakpoints' });
    Object.entries(profile.pollutants).forEach(([pollutant, tables]) => {
        tables.forEach(table => {
            const rows = [];
            let previous = null;
            [...table.thresholds, null].forEach((upper, i) => {
                const from = previous === null ? 0 : previous + 10 ** -table.decimals;
                rows.push([fmtNumber(i + 1), upper === null ? `> ${formatNumber(previous, table.decimals)}`
                    : `${formatNumber(from, table.decimals)} –\u00a0${formatNumber(upper, table.decimals)}`]);
                previous = upper;
            });
            container.append(element('h4', {}, `${POLLUTANT_LABELS[pollutant]} · ${averagingLabel(table.averaging)} · ${unitLabel(table.unit)}`),
                tableOf([t('col_level'), t('col_concentration')], rows));
        });
    });
    return container;
}

/** Terms of an additive risk profile (Canada AQHI). */
function riskTermsTable(profile) {
    return element('div', { className: 'breakpoints' },
        element('p', { className: 'settings-note' }, t('settings_risk_formula').replace('{factor}', formatNumber(profile.scale_factor, 2))),
        tableOf([t('col_pollutant'), t('col_averaging'), t('col_unit'), 'β'], Object.entries(profile.terms).map(([pollutant, term]) =>
            [POLLUTANT_LABELS[pollutant], averagingLabel(term.averaging), unitLabel(term.unit), formatNumber(term.beta)])));
}

/** Breakpoint tables of an index profile, or concentration levels of a concentration profile. */
function breakpointTables(kind, profile) {
    if (profile.kind === 'banded') {
        return thresholdTables(profile);
    }
    if (profile.kind === 'additive_risk') {
        return riskTermsTable(profile);
    }
    const container = element('div', { className: 'breakpoints' });
    Object.entries(profile.pollutants).forEach(([pollutant, spec]) => {
        if (profile.kind === 'concentration') {
            const categories = concentrationCategories(profile, pollutant, effectiveLevels(profile, pollutant, selectedOptions(kind, profile)));
            const ranges = categoryRanges(categories, profile.upper_bound, false, false, spec.decimals);
            container.append(element('h4', {}, `${POLLUTANT_LABELS[pollutant]} · ${averagingLabel(spec.averaging)} · ${unitLabel(spec.unit)}`),
                tableOf([t('col_category'), t('col_concentration')], categories.map((c, i) => [tl(c.name), ranges[i]])));
            return;
        }
        spec.forEach(table => {
            container.append(element('h4', {}, `${POLLUTANT_LABELS[pollutant]} · ${averagingLabel(table.averaging)} · ${unitLabel(table.unit)}`));
            if (table.note) {
                container.append(element('p', { className: 'settings-note' }, tl(table.note)));
            }
            container.append(tableOf([t('col_concentration'), t('col_index')], table.breakpoints.map(([cLow, cHigh, iLow, iHigh]) =>
                [`${formatNumber(cLow, table.decimals)} –\u00a0${formatNumber(cHigh, table.decimals)}`, `${fmtNumber(iLow)} –\u00a0${fmtNumber(iHigh)}`])));
        });
    });
    return container;
}

/** Guideline limits of a noise profile by period (e.g. day and night in a bedroom). */
function noiseLimitsTable(profile) {
    const room = optionValue('noise', profile, profile.limits.option);
    return element('div', { className: 'breakpoints' },
        tableOf([t('col_period'), t('col_hours'), t('col_limit')], profile.limits.values[room].map(period =>
            [t(`period_${period.id}`), `${period.from}–${period.to}`, `${fmtNumber(period.limit)} ${profile.unit}`])));
}

function showSettingsError(message) {
    document.getElementById('settings-error').textContent = message ? t('settings_save_error').replace('{error}', message) : '';
}

async function saveSettings(changes) {
    showSettingsError('');
    try {
        const response = await api('api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(changes),
        });
        const body = await response.json();
        if (!response.ok) {
            throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${response.status}`);
        }
        deviceSettings = body;
    } catch (error) {
        showSettingsError(error.message);
    }
    buildSettingsSections(); // shows the saved (or, on error, the previous) state
}

/** Select of a profile option (e.g. the pollutant, the clothing of the PMV, the room of the noise guidelines). */
function optionField(kind, profile, option) {
    const current = selectedOptions(kind, profile)[option.id] || option.default;
    const select = element('select', { id: `${kind}-option-${option.id}` });
    option.values.forEach(value => {
        let label = option.id === 'pollutant' ? POLLUTANT_LABELS[value] : value;
        if (option.value_labels && option.value_labels[value]) {
            label = tl(option.value_labels[value]);
        } else if (option.unit) {
            label = `${formatNumber(Number(value))} ${option.unit}`;
        }
        const o = element('option', { value }, label);
        o.selected = value === current;
        select.append(o);
    });
    select.addEventListener('change', () => saveSettings({ [`${kind}_profile_options`]: { [profile.id]: { [option.id]: select.value } } }));
    return element('label', { className: 'settings-field' }, element('span', {}, tl(option.label)), select);
}

/** Categories and their value ranges for the legend of a profile. */
function legendContent(kind, profile) {
    if (profile.kind === 'classification') {
        let previous = null;
        const ranges = profile.categories.map((category, i) => {
            let range;
            if (i === 0) {
                range = profile.upper_bound === 'inclusive' ? `≤ ${formatNumber(category.to, profile.decimals)}`
                    : `< ${formatNumber(category.to, profile.decimals)}`;
            } else if (category.to === undefined) {
                range = `${profile.upper_bound === 'inclusive' ? '>' : '≥'} ${formatNumber(previous, profile.decimals)}`;
            } else {
                range = `${profile.upper_bound === 'inclusive' ? '>' : '≥'} ${formatNumber(previous, profile.decimals)} – ${profile.upper_bound === 'inclusive' ? '≤' : '<'} ${formatNumber(category.to, profile.decimals)}`;
            }
            previous = category.to ?? previous;
            return profile.unit ? `${range}\u00a0${unitLabel(profile.unit)}` : range;
        });
        return { categories: profile.categories, ranges };
    }
    if (kind === 'comfort') {
        const convert = v => convertTemperature(v, profile.unit).value;
        const unit = convertTemperature(0, profile.unit).unit;
        const decimals = profile.decimals > 1 ? 1 : (unit !== profile.unit ? 1 : undefined);
        const ranges = categoryRanges(profile.categories, profile.upper_bound, false, false, decimals, convert)
            .map(range => unit ? `${range}\u00a0${unit}` : range);
        return { categories: profile.categories, ranges, neutral: profile.neutral_category };
    }
    if (kind === 'noise') {
        const relative = Boolean(profile.limits);
        let previous = null;
        const ranges = profile.levels.map(([, upper], i) => {
            const format = v => (relative ? (v === 0 ? t('noise_guideline') : `${t('noise_guideline')} + ${fmtNumber(v)}`) : fmtNumber(v));
            const low = profile.upper_bound === 'inclusive' ? ['≤', '>'] : ['<', '≥'];
            let range;
            if (i === 0) {
                range = `${low[0]} ${format(upper)}`;
            } else if (upper === null) {
                range = `${low[1]} ${format(previous)}`;
            } else {
                range = `${format(previous)} –\u00a0${format(upper)}`;
            }
            previous = upper;
            return `${range}\u00a0${relative && i === 0 ? '' : 'dB'}`.trim();
        });
        const categories = profile.levels.map(([id]) => findCategory(profile.categories, id));
        return { categories, ranges };
    }
    if (profile.kind === 'concentration') {
        const options = selectedOptions(kind, profile);
        const pollutantOption = (profile.options || []).find(o => o.id === 'pollutant');
        const pollutant = pollutantOption ? (options.pollutant || pollutantOption.default) : Object.keys(profile.pollutants)[0];
        const spec = profile.pollutants[pollutant];
        const categories = concentrationCategories(profile, pollutant, effectiveLevels(profile, pollutant, options));
        const ranges = categoryRanges(categories, profile.upper_bound, false, false, spec.decimals)
            .map(range => `${range}\u00a0${unitLabel(spec.unit)}`);
        return { categories, ranges };
    }
    if (profile.kind === 'banded') {
        let previous = 0;
        const ranges = profile.categories.map(c => {
            const range = c.to - previous === 1 ? fmtNumber(c.to) : `${fmtNumber(previous + 1)} –\u00a0${fmtNumber(c.to)}`;
            previous = c.to;
            return range;
        });
        return { categories: profile.categories, ranges };
    }
    const ranges = categoryRanges(profile.categories, profile.upper_bound, true, hasDisplayOnlyTopBand(profile));
    if (profile.kind === 'additive_risk') {
        ranges[0] = `${fmtNumber(profile.index_min)} –\u00a0${fmtNumber(profile.categories[0].to)}`;
    }
    return { categories: profile.categories, ranges };
}

/** One profile section: selector, options, description, legend, tables, reference. */
function profileSection({ kind, container: containerId, title }) {
    const container = document.getElementById(containerId);
    const settingKey = `${kind}_profile`;
    const selectedId = deviceSettings[settingKey];
    const profile = profiles[kind][selectedId];
    container.innerHTML = '';
    container.append(element('h3', {}, t(title)), element('p', { className: 'settings-hint' }, t('settings_device_hint')));

    const select = element('select', { id: `${kind}-profile-select` });
    Object.values(profiles[kind]).forEach(p => {
        const option = element('option', { value: p.id }, tl(p.name));
        option.selected = p.id === selectedId;
        select.append(option);
    });
    select.addEventListener('change', () => saveSettings({ [settingKey]: select.value }));
    container.append(element('label', { className: 'settings-field' }, element('span', {}, t('settings_profile')), select));
    if (!profile) {
        return;
    }
    (profile.options || []).forEach(option => container.append(optionField(kind, profile, option)));
    container.append(element('p', { className: 'settings-description' }, tl(profile.description)));

    const { categories, ranges, neutral } = legendContent(kind, profile);
    container.append(element('details', { open: '' }, element('summary', {}, t('settings_categories')), legendTable(categories, ranges, neutral)));
    if (kind === 'aqi' || kind === 'co2') {
        container.append(element('details', {}, element('summary', {}, t('settings_breakpoints')), breakpointTables(kind, profile)));
    } else if (kind === 'noise' && profile.limits) {
        container.append(element('details', {}, element('summary', {}, t('settings_noise_limits')), noiseLimitsTable(profile)));
    }
    container.append(element('p', { className: 'settings-reference' }, `${t('settings_reference')}: ${profile.reference}`));
}

async function fetchJson(path) {
    const response = await api(path);
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
}

/** Dust sensors: PM2.5 humidity correction (device-wide) and health of the sensors. */
async function dustSection(container) {
    container.innerHTML = '';
    container.append(element('h3', {}, t('settings_dust_section')), element('p', { className: 'settings-hint' }, t('settings_device_hint')));
    const correction = element('select', { id: 'pm25-correction-select' });
    ['barkjohn_2021', 'epa_2022_extended', 'none'].forEach(value => {
        const o = element('option', { value }, t(`pm25_correction_${value}`));
        o.selected = value === deviceSettings.pm25_correction;
        correction.append(o);
    });
    correction.addEventListener('change', () => saveSettings({ pm25_correction: correction.value }));
    container.append(element('label', { className: 'settings-field' }, element('span', {}, t('settings_pm25_correction')), correction),
        element('p', { className: 'settings-note' }, t('settings_pm25_correction_note')));

    const statusBox = element('div', { className: 'dust-status', id: 'dust-status' }, t('loading'));
    container.append(element('h4', {}, t('settings_dust_health')), statusBox);
    let status;
    try {
        status = await fetchJson('api/dust-sensors');
    } catch (error) {
        statusBox.textContent = t('settings_save_error').replace('{error}', error.message);
        return;
    }
    statusBox.innerHTML = '';
    const rows = [[t('dust_state'), t(`dust_state_${status.state || 'learning'}`)]];
    if (status.baseline_start) {
        rows.push([t('dust_baseline_since'), localizedParams({ since: status.baseline_start }).since]);
    }
    rows.push([t('dust_days'), fmtNumber(status.days ?? 0)]);
    if (status.baseline_ratio !== null && status.baseline_ratio !== undefined) {
        rows.push([t('dust_ratio'), `${fmtNumber(status.baseline_ratio, 2)} → ${fmtNumber(status.recent_ratio, 2)} (${status.drift >= 0 ? '+' : ''}${fmtNumber(status.drift * 100)} %)`]);
    }
    if (status.recent_correlation !== null && status.recent_correlation !== undefined) {
        rows.push([t('dust_correlation'), fmtNumber(status.recent_correlation, 2)]);
    }
    if (status.hourly) {
        rows.push([t('dust_disagreement'), t('dust_disagreement_hours')
            .replace('{flagged}', fmtNumber(status.hourly.flagged_hours)).replace('{valid}', fmtNumber(status.hourly.valid_hours))]);
    }
    statusBox.append(element('table', { className: 'settings-table' },
        element('tbody', {}, ...rows.map(([k, v]) => element('tr', {}, element('th', { scope: 'row' }, k), element('td', {}, v))))));
    (status.alarms || []).forEach(alarm => statusBox.append(
        element('p', { className: 'dust-alarm' }, fillParams(t(`maintenance_${alarm.code}`), localizedParams(alarm.params)))));
    if (status.state === 'learning') {
        statusBox.append(element('p', { className: 'settings-note' }, t('dust_learning_note')));
    }
    const reset = element('button', { type: 'button', className: 'settings-button', id: 'dust-reset' }, t('dust_reset'));
    reset.addEventListener('click', async () => {
        if (!confirm(t('dust_reset_confirm'))) {
            return;
        }
        try {
            const response = await api('api/dust-sensors/reset', { method: 'POST' });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
        } catch (error) {
            showSettingsError(error.message);
        }
        setTimeout(() => dustSection(container), 500);
    });
    container.append(reset, element('p', { className: 'settings-note' }, t('dust_reset_note')));
}

/** Validation of all the sensors with their history. */
async function healthSection(container) {
    container.innerHTML = '';
    container.append(element('h3', {}, t('settings_health_section')), element('p', { className: 'settings-hint' }, t('settings_health_hint')));
    let report;
    try {
        report = await fetchJson('api/sensor-health');
    } catch (error) {
        container.append(element('p', {}, t('settings_save_error').replace('{error}', error.message)));
        return;
    }
    const icons = { ok: 'sev-ok', warning: 'sev-mid', alarm: 'sev-high', no_data: 'sev-low' };
    const colors = { ok: '#009E73', warning: '#F0E442', alarm: '#D55E00', no_data: '#9E9E9E' };
    const rows = (report.sensors || []).map(sensor => {
        const badge = element('span', { className: 'cat-badge', 'aria-hidden': 'true' });
        setBadge(badge, { color: colors[sensor.status], cvd_color: colors[sensor.status] }, icons[sensor.status]);
        badge.removeAttribute('title');
        const issues = sensor.issues.map(issue => element('li', {},
            fillParams(t(`${issue.dust ? 'maintenance' : 'validation'}_${issue.code}`), localizedParams(issue.params))));
        return element('tr', {},
            element('th', { scope: 'row' }, `${SENSOR_NAMES[sensor.id] || sensor.id}`, element('br'),
                element('span', { className: 'sensor-role' }, t(`sensor_role_${sensor.id}`))),
            element('td', {}, badge, ' ', t(`health_${sensor.status}`), issues.length ? element('ul', { className: 'issue-list' }, ...issues) : ''));
    });
    container.append(element('table', { className: 'settings-table health' },
        element('thead', {}, element('tr', {}, element('th', {}, t('col_sensor')), element('th', {}, t('col_status')))),
        element('tbody', {}, ...rows)));
    if (report.evaluated) {
        container.append(element('p', { className: 'settings-note' }, t('health_evaluated').replace('{time}', fmtDateTime(report.evaluated))));
    }
    const reset = element('button', { type: 'button', className: 'settings-button', id: 'health-reset' }, t('health_reset'));
    reset.addEventListener('click', async () => {
        if (!confirm(t('health_reset_confirm'))) {
            return;
        }
        await api('api/sensor-health/reset', { method: 'POST' });
        setTimeout(() => healthSection(container), 500);
    });
    container.append(reset, element('p', { className: 'settings-note' }, t('health_reset_note')));
}

/** Account: change of the password of the logged in user (the session ends, the user logs in again). */
async function accountSection(container) {
    container.innerHTML = '';
    let status;
    try {
        status = await fetchJson('api/auth/status');
    } catch (error) {
        return;
    }
    document.getElementById('tab-account').hidden = !status.enabled;
    if (!status.enabled) {
        if (selectedSettingsTab() === 'account') {
            selectSettingsTab('air');
        }
        return;
    }
    container.append(element('h3', {}, t('settings_account_section')),
        element('p', { className: 'settings-hint' }, t('account_logged_in').replace('{user}', status.user)));
    const username = element('input', { type: 'text', id: 'account-username', autocomplete: 'username', value: status.user, hidden: '' });
    const current = element('input', { type: 'password', id: 'current-password', autocomplete: 'current-password', required: '' });
    const next = element('input', { type: 'password', id: 'new-password', autocomplete: 'new-password', required: '' });
    const repeat = element('input', { type: 'password', id: 'repeat-new-password', autocomplete: 'new-password', required: '' });
    const message = element('p', { className: 'settings-error', role: 'alert', id: 'account-message' });
    const field = (label, input) => element('div', { className: 'settings-field password-row' },
        element('label', { for: input.id }, label), input);
    const form = element('form', { className: 'account-form' }, username,
        field(t('current_password'), current), field(t('new_password'), next), field(t('repeat_password'), repeat),
        element('p', { className: 'settings-note' }, t('password_change_logout_note')),
        element('button', { type: 'submit', className: 'settings-button' }, t('change_password')), message);
    container.append(form);
    [current, next, repeat].forEach(addPasswordToggle);
    const meter = attachStrengthMeter(next, () => [status.user]);
    const fail = (code, input) => {
        const [key, seconds] = String(code).split(':');
        message.textContent = t(`auth_error_${key}`).replace('{seconds}', seconds || '')
            .replace('{min}', passwordPolicy ? passwordPolicy.min_length : 10);
        if (input) {
            input.focus();
        }
    };
    form.addEventListener('submit', async event => {
        event.preventDefault();
        message.textContent = '';
        const strength = meter.evaluate();
        const policyError = strength ? passwordPolicyError(strength) : null;
        if (policyError) {
            fail(policyError, next);
            return;
        }
        if (next.value !== repeat.value) {
            fail('passwords_differ', repeat);
            return;
        }
        if (next.value === current.value) {
            fail('password_unchanged', next);
            return;
        }
        const response = await api('api/account/password', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: current.value, new_password: next.value }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
            fail(body.detail, current);
            return;
        }
        // the server has ended the session: log in again with the new password
        globalThis.location.href = 'login?changed=1';
    });
}

/** Restores the recommended profiles (device) and the display options of this browser. */
async function restoreDefaults() {
    if (!confirm(t('settings_restore_confirm'))) {
        return;
    }
    try {
        const response = await api('api/settings/restore', { method: 'POST' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        deviceSettings = await response.json();
    } catch (error) {
        showSettingsError(error.message);
    }
    ['temperatureUnit', 'palette', 'showDustTiles'].forEach(key => localStorage.removeItem(key));
    applyDustTilesVisibility();
    applyPalette();
    rerender();
    buildSettingsSections();
}

function buildSettingsSections() {
    if (!deviceSettings) {
        return;
    }
    PROFILE_SECTIONS.forEach(profileSection);
    dustSection(document.getElementById('settings-dust'));
    healthSection(document.getElementById('settings-health'));
    accountSection(document.getElementById('settings-account'));
    document.getElementById('show-dust-tiles').checked = showDustTiles();
    document.getElementById('temperature-unit-select').value = temperatureUnit();
    document.getElementById('palette-select').value = palette();
}

// ---------------------------------------------------------------- tabs

const settingsTabs = () => [...document.querySelectorAll('#settings-dialog [role="tab"]')].filter(tab => !tab.hidden);

function selectedSettingsTab() {
    return sessionStorage.getItem('settingsTab') || 'air';
}

/** Shows the panel of a tab ("air", "co2", "noise", "comfort", "uv", "voc", "sensors", "display", "account"). */
function selectSettingsTab(name, focus = false) {
    let tab = document.getElementById(`tab-${name}`);
    if (!tab || tab.hidden) {
        tab = document.getElementById('tab-air');
    }
    document.querySelectorAll('#settings-dialog [role="tab"]').forEach(other => {
        const selected = other === tab;
        other.setAttribute('aria-selected', selected ? 'true' : 'false');
        other.tabIndex = selected ? 0 : -1;
        document.getElementById(other.getAttribute('aria-controls')).hidden = !selected;
    });
    sessionStorage.setItem('settingsTab', tab.id.slice(4));
    document.querySelector('#settings-dialog .settings-body').scrollTop = 0;
    if (focus) {
        tab.focus();
    }
}

function initSettingsTabs() {
    const tablist = document.querySelector('#settings-dialog [role="tablist"]');
    tablist.addEventListener('click', event => {
        const tab = event.target.closest('[role="tab"]');
        if (tab) {
            selectSettingsTab(tab.id.slice(4));
        }
    });
    // arrow keys, Home and End move between the tabs (automatic activation)
    tablist.addEventListener('keydown', event => {
        const tabs = settingsTabs();
        const index = tabs.indexOf(document.activeElement);
        if (index < 0) {
            return;
        }
        const target = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 }[event.key];
        if (target === undefined) {
            return;
        }
        event.preventDefault();
        const next = tabs[(target + tabs.length) % tabs.length];
        selectSettingsTab(next.id.slice(4), true);
    });
}

async function openSettings() {
    const dialog = document.getElementById('settings-dialog');
    showSettingsError('');
    try {
        deviceSettings = await fetchJson('api/settings');
    } catch (error) {
        showSettingsError(error.message);
    }
    buildSettingsSections();
    selectSettingsTab(selectedSettingsTab());
    if (!dialog.open) {
        dialog.showModal();
        document.querySelector('#settings-dialog [role="tab"][aria-selected="true"]').focus();
    }
}

function initSettings() {
    const dialog = document.getElementById('settings-dialog');
    initSettingsTabs();
    document.getElementById('settings-btn').addEventListener('click', openSettings);
    document.getElementById('settings-close').addEventListener('click', () => dialog.close());
    // close when clicking on the backdrop
    dialog.addEventListener('click', event => {
        if (event.target === dialog) {
            dialog.close();
        }
    });
    document.getElementById('show-dust-tiles').addEventListener('change', event => {
        localStorage.setItem('showDustTiles', event.target.checked ? 'true' : 'false');
        applyDustTilesVisibility();
    });
    document.getElementById('temperature-unit-select').addEventListener('change', event => {
        localStorage.setItem('temperatureUnit', event.target.value);
        rerender();
        buildSettingsSections();
    });
    document.getElementById('palette-select').addEventListener('change', event => {
        localStorage.setItem('palette', event.target.value);
        applyPalette();
        rerender();
        buildSettingsSections();
    });
    document.getElementById('restore-defaults').addEventListener('click', restoreDefaults);
}
