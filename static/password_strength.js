// password_strength.js - password strength estimation, same algorithm as password_strength.py
// (the browser shows the strength while typing, the server enforces the policy).

/* global module */

function asciiLower(c) {
    return c >= 'A' && c <= 'Z' ? String.fromCharCode(c.charCodeAt(0) + 32) : c;
}

function isAsciiPrintable(c) {
    const code = c.codePointAt(0);
    return code >= 32 && code <= 126;
}

function poolSize(chars) {
    let size = 0;
    if (chars.some(c => c >= 'a' && c <= 'z')) {
        size += 26;
    }
    if (chars.some(c => c >= 'A' && c <= 'Z')) {
        size += 26;
    }
    if (chars.some(c => c >= '0' && c <= '9')) {
        size += 10;
    }
    if (chars.some(c => isAsciiPrintable(c) && !/[A-Za-z0-9]/.test(c))) {
        size += 33;
    }
    if (chars.some(c => !isAsciiPrintable(c))) {
        size += 100;
    }
    return size;
}

function sequential(a, b, direction, rows) {
    return rows.some(row => {
        for (let i = row.indexOf(a); i !== -1; i = row.indexOf(a, i + 1)) {
            const j = i + direction;
            if (j >= 0 && j < row.length && row[j] === b) {
                return true;
            }
        }
        return false;
    });
}

/**
 * Strength of a password: {score: 0-4, bits, feedback: [codes], acceptable}.
 * context: user-specific words (e.g. the user name) that must not be used.
 * policy: static/password_policy.json
 */
function evaluatePassword(password, context, policy) {
    const chars = Array.from(password || ''); // code points, like the Python implementation
    const n = chars.length;
    const feedback = [];
    const add = code => {
        if (!feedback.includes(code)) {
            feedback.push(code);
        }
    };
    if (n < policy.min_length) {
        add('too_short');
    }
    if (n > policy.max_length) {
        add('too_long');
    }
    if (n === 0) {
        return { score: 0, bits: 0, feedback, acceptable: false };
    }

    const lower = chars.map(asciiLower);
    const variants = ['i', 'l'].map(one => lower.map(c => (c === '1' ? one : (policy.leet[c] || c))));

    // the context words first (preferred over a common word of the same length)
    const candidates = [];
    (context || []).forEach(word => {
        const normalized = Array.from(word || '').map(asciiLower).join('');
        if (Array.from(normalized).length >= 3) {
            candidates.push([normalized, 'user_name']);
        }
    });
    policy.words.forEach(word => candidates.push([word, 'common']));

    const covered = new Array(n).fill(false);
    let dictionaryBits = 0;
    for (let i = 0; i < n;) {
        let best = null;
        for (const [word, code] of candidates) {
            const letters = Array.from(word);
            const length = letters.length;
            if (length > n - i || (best && length <= best.length)) {
                continue;
            }
            for (const reverse of [false, true]) {
                const target = reverse ? letters.slice().reverse().join('') : word;
                if (variants.some(v => v.slice(i, i + length).join('') === target)) {
                    best = { length, code, reverse };
                    break;
                }
            }
        }
        if (best) {
            for (let k = i; k < i + best.length; k++) {
                covered[k] = true;
            }
            dictionaryBits += policy.dictionary_bits + (best.reverse ? 1 : 0);
            add(best.code);
            i += best.length;
        } else {
            i += 1;
        }
    }

    // years
    for (let i = 0; i <= n - 4;) {
        const digits = chars.slice(i, i + 4);
        if (!covered.slice(i, i + 4).some(Boolean) && digits.every(c => c >= '0' && c <= '9')
            && Number(digits.join('')) >= 1900 && Number(digits.join('')) <= 2099) {
            for (let k = i; k < i + 4; k++) {
                covered[k] = true;
            }
            dictionaryBits += policy.year_bits;
            add('years');
            i += 4;
        } else {
            i += 1;
        }
    }

    // remaining characters, repeats and sequences count less
    const rows = policy.sequences;
    let effective = 0;
    let repeatRun = 1;
    for (let i = 0; i < n; i++) {
        if (covered[i]) {
            repeatRun = 1;
            continue;
        }
        let weight = 1;
        if (i > 0 && !covered[i - 1] && chars[i] === chars[i - 1]) {
            repeatRun += 1;
            weight = 0.25;
            if (repeatRun >= 3) {
                add('repeats');
            }
        } else {
            repeatRun = 1;
            if (i > 1 && !covered[i - 1] && !covered[i - 2]) {
                for (const direction of [1, -1]) {
                    if (sequential(lower[i - 2], lower[i - 1], direction, rows) && sequential(lower[i - 1], lower[i], direction, rows)) {
                        weight = 0.25;
                        add('sequences');
                        break;
                    }
                }
            }
        }
        effective += weight;
    }

    const bits = effective * Math.log2(poolSize(chars)) + dictionaryBits;
    let score = policy.score_bits.filter(threshold => bits >= threshold).length;
    if (n < policy.min_length) {
        score = Math.min(score, 1);
    }
    if (score < policy.min_score && !['user_name', 'common', 'years', 'repeats', 'sequences'].some(c => feedback.includes(c))) {
        add('longer');
    }
    const acceptable = n >= policy.min_length && n <= policy.max_length && score >= policy.min_score;
    return { score, bits: Math.round(bits * 10) / 10, feedback, acceptable };
}

if (typeof module !== 'undefined') {
    module.exports = { evaluatePassword };
}
