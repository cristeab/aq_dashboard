// common.js - parts shared by the dashboard and the login page: language menu,
// password fields (show/hide button, strength meter). Uses the t() function of the page.

/* global t, evaluatePassword */

// ---------------------------------------------------------------- language menu

/**
 * Language button with its dropdown (.language-container). onSelect(lang) is awaited
 * before the menu closes. Returns {close, setActive(lang)}.
 */
function initLanguageMenu(container, onSelect) {
    const button = container.querySelector('.language-btn');
    const dropdown = container.querySelector('.language-dropdown');
    const options = [...dropdown.querySelectorAll('.language-option')];
    const setOpen = open => {
        dropdown.classList.toggle('hidden', !open);
        button.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    button.addEventListener('click', event => {
        const open = dropdown.classList.contains('hidden');
        setOpen(open);
        if (open) {
            (options.find(o => o.classList.contains('active')) || options[0]).focus();
        }
        event.stopPropagation();
    });
    options.forEach(option => option.addEventListener('click', async event => {
        event.stopPropagation();
        await onSelect(option.dataset.lang);
        setOpen(false);
        button.focus();
    }));
    dropdown.addEventListener('keydown', event => {
        const index = options.indexOf(document.activeElement);
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            const next = (index + (event.key === 'ArrowDown' ? 1 : options.length - 1)) % options.length;
            options[next].focus();
        }
    });
    document.addEventListener('click', event => {
        if (!container.contains(event.target)) {
            setOpen(false);
        }
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !dropdown.classList.contains('hidden')) {
            setOpen(false);
            button.focus();
        }
    });
    return {
        close: () => setOpen(false),
        setActive(lang) {
            options.forEach(option => {
                const active = option.dataset.lang === lang;
                option.classList.toggle('active', active);
                option.setAttribute('aria-current', active ? 'true' : 'false');
            });
            container.querySelector('.language-active-code').textContent = lang.toUpperCase();
            // the visible code is part of the accessible name (speech recognition users say what they see)
            button.setAttribute('aria-label', `${lang.toUpperCase()} – ${t('select_language')}`);
            button.title = t('select_language');
        },
    };
}

// ---------------------------------------------------------------- password fields

const EYE_ICON = '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><path class="line" d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle class="line" cx="12" cy="12" r="3"/></svg>';
const EYE_OFF_ICON = '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><path class="line" d="M10.6 5.1A10.8 10.8 0 0 1 12 5c6.4 0 10 7 10 7a17.6 17.6 0 0 1-2.9 3.9M6.6 6.6C3.9 8.4 2 12 2 12s3.6 7 10 7a9.7 9.7 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18"/></svg>';

function updatePasswordToggle(button) {
    const input = document.getElementById(button.getAttribute('aria-controls'));
    const visible = input.type === 'text';
    button.innerHTML = visible ? EYE_OFF_ICON : EYE_ICON;
    button.setAttribute('aria-pressed', visible ? 'true' : 'false');
    // a fixed name with aria-pressed: the state is announced by screen readers
    button.setAttribute('aria-label', t('show_password'));
    button.title = visible ? t('hide_password') : t('show_password');
}

/** Button in a password field to show the password in clear text (and hide it again). */
function addPasswordToggle(input) {
    const wrapper = document.createElement('div');
    wrapper.className = 'password-field';
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'password-toggle';
    button.setAttribute('aria-controls', input.id);
    wrapper.appendChild(button);
    updatePasswordToggle(button);
    button.addEventListener('click', () => {
        const start = input.selectionStart;
        const end = input.selectionEnd;
        input.type = input.type === 'password' ? 'text' : 'password';
        updatePasswordToggle(button);
        input.focus();
        if (start !== null) {
            input.setSelectionRange(start, end);
        }
    });
    // never leave a password visible in a form that is sent (browsers could store it as text)
    input.form?.addEventListener('submit', () => {
        if (input.type === 'text') {
            input.type = 'password';
            updatePasswordToggle(button);
        }
    });
    return button;
}

/** Hides the passwords shown in clear text (e.g. when a form is reset). */
function hidePasswords(root = document) {
    root.querySelectorAll('.password-toggle').forEach(button => {
        document.getElementById(button.getAttribute('aria-controls')).type = 'password';
        updatePasswordToggle(button);
    });
}

// ---------------------------------------------------------------- password strength

let passwordPolicy = null;

async function loadPasswordPolicy() {
    if (!passwordPolicy) {
        passwordPolicy = await (await fetch('static/password_policy.json')).json();
    }
    return passwordPolicy;
}

/** Error code of the server for a password that does not satisfy the policy (null if it does). */
function passwordPolicyError(strength) {
    if (strength.acceptable) {
        return null;
    }
    if (strength.feedback.includes('too_short')) {
        return 'password_too_short';
    }
    return strength.feedback.includes('too_long') ? 'password_too_long' : 'password_too_weak';
}

/**
 * Strength meter below a new password field, updated while typing.
 * contextWords(): words that must not be used (the user name).
 * Returns {evaluate(), refresh()}: evaluate() gives the strength of the current value.
 */
function attachStrengthMeter(input, contextWords = () => []) {
    const meter = document.createElement('div');
    meter.className = 'strength';
    meter.dataset.score = '';
    meter.innerHTML = `
        <div class="strength-bar" aria-hidden="true">${'<span></span>'.repeat(5)}</div>
        <p class="strength-text" id="${input.id}-strength" aria-live="polite"></p>
        <ul class="strength-hints" id="${input.id}-hints"></ul>`;
    (input.closest('.password-field') || input).after(meter);
    input.setAttribute('aria-describedby', `${input.id}-strength ${input.id}-hints`);
    const text = meter.querySelector('.strength-text');
    const hints = meter.querySelector('.strength-hints');

    const evaluate = () => (passwordPolicy ? evaluatePassword(input.value, contextWords(), passwordPolicy) : null);
    const refresh = () => {
        const strength = evaluate();
        if (!strength || !input.value) {
            meter.dataset.score = '';
            text.textContent = passwordPolicy ? t('strength_requirement').replace('{min}', passwordPolicy.min_length) : '';
            hints.innerHTML = '';
            return;
        }
        meter.dataset.score = String(strength.score);
        meter.classList.toggle('unacceptable', !strength.acceptable);
        text.textContent = `${t('strength_label')}: ${t(`strength_${strength.score}`)}`
            + (strength.acceptable ? '' : ` – ${t('strength_not_accepted')}`);
        // hints only while the password is not good yet (e.g. not "avoid sequences" for a strong one)
        const codes = strength.acceptable && strength.score >= 3 ? [] : [...strength.feedback];
        if (strength.acceptable && strength.score < 3) {
            codes.push('passphrase');
        }
        hints.innerHTML = '';
        codes.forEach(code => {
            const item = document.createElement('li');
            item.textContent = t(`strength_hint_${code}`).replace('{min}', passwordPolicy.min_length)
                .replace('{max}', passwordPolicy.max_length);
            hints.appendChild(item);
        });
    };
    input.addEventListener('input', refresh);
    loadPasswordPolicy().then(refresh).catch(() => {});
    return { evaluate, refresh };
}
