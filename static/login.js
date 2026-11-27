// login.js - login page, first-run setup of the administrator account and change of a
// default or temporary password after the first login

/* global initLanguageMenu, addPasswordToggle, updatePasswordToggle, hidePasswords, attachStrengthMeter, loadPasswordPolicy,
   passwordPolicyError, passwordPolicy */

let translations = {};
let language = localStorage.getItem('language') || 'en';
let languageMenu = null;
const strengthMeters = [];

function t(key) {
    return (translations[language] || {})[key] || (translations.en || {})[key] || key;
}

async function loadLanguage(lang) {
    if (!translations[lang]) {
        try {
            translations[lang] = await (await fetch(`static/translations_${lang}.json`)).json();
        } catch (error) {
            translations[lang] = {};
        }
    }
}

let lastError = '';
let lastInfo = '';

async function setLanguage(lang) {
    await loadLanguage(lang);
    language = lang;
    localStorage.setItem('language', lang);
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    document.title = t('login_title');
    languageMenu?.setActive(lang);
    document.querySelectorAll('.password-toggle').forEach(updatePasswordToggle);
    strengthMeters.forEach(meter => meter.refresh());
    showError(lastError);
    showInfo(lastInfo);
}

function errorText(detail) {
    const [code, seconds] = String(detail).split(':');
    const min = passwordPolicy ? passwordPolicy.min_length : 10;
    return t(`auth_error_${code}`).replace('{seconds}', seconds || '').replace('{min}', min);
}

function showError(detail) {
    lastError = detail || '';
    document.getElementById('login-error').textContent = detail ? errorText(detail) : '';
}

/** Information above the forms, e.g. after a change of the password. */
function showInfo(key) {
    lastInfo = key || '';
    document.getElementById('login-info').textContent = key ? t(key) : '';
}

async function post(path, body) {
    const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error(typeof data.detail === 'string' ? data.detail : 'invalid_credentials');
        error.status = response.status;
        throw error;
    }
    return data;
}

const forms = () => ['login-form', 'setup-form', 'change-form'].map(id => document.getElementById(id));

function showForm(id, focusId) {
    forms().forEach(form => { form.hidden = form.id !== id; });
    hidePasswords();
    document.getElementById(focusId).focus();
}

/** New password and its repetition: same value and policy of the server. Returns an error code or null. */
function newPasswordError(meter, password, repeat) {
    const strength = meter.evaluate();
    const error = strength ? passwordPolicyError(strength) : null;
    if (error) {
        return error;
    }
    return password === repeat ? null : 'passwords_differ';
}

document.addEventListener('DOMContentLoaded', async () => {
    const theme = localStorage.getItem('theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.body.classList.toggle('dark-theme', theme === 'dark');
    const palette = localStorage.getItem('palette') === 'cvd' ? 'cvd' : 'official';
    document.body.classList.add(`palette-${palette}`);
    languageMenu = initLanguageMenu(document.querySelector('.language-container'), setLanguage);
    ['password', 'new-password', 'repeat-password', 'change-current', 'change-new', 'change-repeat']
        .forEach(id => addPasswordToggle(document.getElementById(id)));
    const setupMeter = attachStrengthMeter(document.getElementById('new-password'), () => [document.getElementById('new-username').value]);
    const changeMeter = attachStrengthMeter(document.getElementById('change-new'), () => [document.getElementById('change-username').value]);
    strengthMeters.push(setupMeter, changeMeter);
    document.getElementById('new-username').addEventListener('input', setupMeter.refresh);
    // an error message is outdated as soon as the user edits the form
    forms().forEach(form => form.addEventListener('input', () => showError('')));
    await loadLanguage('en');
    await setLanguage(language);
    await loadPasswordPolicy().catch(() => null);

    const status = await (await fetch('api/auth/status')).json();
    if (!status.enabled || (status.user && !status.must_change_password)) {
        location.href = './';
        return;
    }

    // password kept between the login and the change of a default password (not asked twice)
    let loginPassword = null;
    const showChangeForm = (username, currentPassword) => {
        loginPassword = currentPassword;
        document.getElementById('change-username').value = username;
        const currentField = document.getElementById('change-current-field');
        currentField.hidden = currentPassword !== null;
        document.getElementById('change-current').required = currentPassword === null;
        changeMeter.refresh();
        showForm('change-form', currentPassword === null ? 'change-current' : 'change-new');
    };

    if (status.setup_required) {
        showForm('setup-form', 'setup-code');
    } else if (status.user && status.must_change_password) {
        showChangeForm(status.user, null);
    } else {
        showForm('login-form', 'username');
        if (new URLSearchParams(location.search).get('changed')) {
            showInfo('password_changed_login');
        }
    }

    document.getElementById('login-form').addEventListener('submit', async event => {
        event.preventDefault();
        showError('');
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        try {
            const result = await post('api/login', { username, password, remember: document.getElementById('remember').checked });
            if (result.must_change_password) {
                showInfo('');
                document.getElementById('password').value = '';
                showChangeForm(result.user, password);
                return;
            }
            location.href = './';
        } catch (error) {
            showError(error.message);
            document.getElementById('password').select();
        }
    });

    document.getElementById('setup-form').addEventListener('submit', async event => {
        event.preventDefault();
        showError('');
        const password = document.getElementById('new-password').value;
        const error = newPasswordError(setupMeter, password, document.getElementById('repeat-password').value);
        if (error) {
            showError(error);
            document.getElementById(error === 'passwords_differ' ? 'repeat-password' : 'new-password').focus();
            return;
        }
        try {
            await post('api/setup', {
                setup_code: document.getElementById('setup-code').value,
                username: document.getElementById('new-username').value,
                password,
            });
            location.href = './';
        } catch (error) {
            showError(error.message);
        }
    });

    document.getElementById('change-form').addEventListener('submit', async event => {
        event.preventDefault();
        showError('');
        const password = document.getElementById('change-new').value;
        const current = loginPassword ?? document.getElementById('change-current').value;
        let error = newPasswordError(changeMeter, password, document.getElementById('change-repeat').value);
        if (!error && password === current) {
            error = 'password_unchanged';
        }
        if (error) {
            showError(error);
            document.getElementById(error === 'passwords_differ' ? 'change-repeat' : 'change-new').focus();
            return;
        }
        try {
            await post('api/account/password', { current_password: current, new_password: password });
        } catch (error) {
            if (error.status === 401) { // the session has ended: log in again
                showForm('login-form', 'username');
            }
            showError(error.message);
            return;
        }
        // the session ends with the change: log in with the new password
        const username = document.getElementById('change-username').value;
        loginPassword = null;
        ['change-current', 'change-new', 'change-repeat'].forEach(id => { document.getElementById(id).value = ''; });
        changeMeter.refresh();
        document.getElementById('username').value = username;
        showInfo('password_changed_login');
        showForm('login-form', 'password');
    });

    document.getElementById('change-cancel').addEventListener('click', async () => {
        await fetch('api/logout', { method: 'POST' }).catch(() => {});
        loginPassword = null;
        showError('');
        showInfo('');
        showForm('login-form', 'username');
    });
});
