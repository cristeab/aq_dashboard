#!/usr/bin/env python3
"""
Password strength estimation, same algorithm as static/password_strength.js
(the browser shows the strength while typing, the server enforces it).

The strength is an estimate of the entropy in bits:
- character pool: lowercase, uppercase, digits, symbols, other characters;
- common passwords and words, the user name, also reversed or with letter
  substitutions (p@ssw0rd), count as one guess from a list (~10 bits) instead
  of their characters;
- years (1900-2099) count ~7 bits;
- repeated characters (aaa) and sequences (abc, 321, qwerty) count 1/4 of a
  character from the third one on.

Scores: 0 very weak, 1 weak, 2 fair, 3 good, 4 strong (bits thresholds of the
policy). The policy (static/password_policy.json) requires a minimum length
and score.
"""

import json
import math
import os
from typing import Dict, Iterable, List, Optional

POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "password_policy.json")

_policy: Optional[Dict] = None


def policy() -> Dict:
    global _policy
    if _policy is None:
        with open(POLICY_PATH, encoding="utf-8") as f:
            _policy = json.load(f)
    return _policy


def _ascii_lower(c: str) -> str:
    return chr(ord(c) + 32) if "A" <= c <= "Z" else c


def _pool_size(chars: List[str]) -> int:
    size = 0
    if any("a" <= c <= "z" for c in chars):
        size += 26
    if any("A" <= c <= "Z" for c in chars):
        size += 26
    if any("0" <= c <= "9" for c in chars):
        size += 10
    if any(32 <= ord(c) <= 126 and not c.isalnum() for c in chars):
        size += 33
    if any(not (32 <= ord(c) <= 126) for c in chars):
        size += 100
    return size


def _sequential(a: str, b: str, direction: int, rows: List[str]) -> bool:
    for row in rows:
        i = row.find(a)
        while i != -1:
            j = i + direction
            if 0 <= j < len(row) and row[j] == b:
                return True
            i = row.find(a, i + 1)
    return False


def evaluate(password: str, context: Iterable[str] = (), pol: Optional[Dict] = None) -> Dict:
    """Strength of a password: {"score": 0-4, "bits": float, "feedback": [codes], "acceptable": bool}.
    context: user-specific words (e.g. the user name) that must not be used."""
    pol = pol or policy()
    chars = list(password or "")
    n = len(chars)
    feedback: List[str] = []

    def add(code):
        if code not in feedback:
            feedback.append(code)

    if n < pol["min_length"]:
        add("too_short")
    if n > pol["max_length"]:
        add("too_long")
    if n == 0:
        return {"score": 0, "bits": 0.0, "feedback": feedback, "acceptable": False}

    lower = [_ascii_lower(c) for c in chars]
    leet = pol["leet"]
    variants = []
    for one in ("i", "l"):
        variants.append([one if c == "1" else leet.get(c, c) for c in lower])

    # words to look for: the context words first (preferred over a common word of the same length)
    candidates = []
    for word in context:
        word = "".join(_ascii_lower(c) for c in (word or ""))
        if len(word) >= 3:
            candidates.append((word, "user_name"))
    candidates += [(word, "common") for word in pol["words"]]

    covered = [False] * n
    dictionary_bits = 0.0
    i = 0
    while i < n:
        best = None  # (length, code, reversed)
        for word, code in candidates:
            length = len(word)
            if length > n - i or (best and length <= best[0]):
                continue
            for reverse in (False, True):
                target = word[::-1] if reverse else word
                if any("".join(v[i:i + length]) == target for v in variants):
                    best = (length, code, reverse)
                    break
        if best:
            length, code, reverse = best
            for k in range(i, i + length):
                covered[k] = True
            dictionary_bits += pol["dictionary_bits"] + (1 if reverse else 0)
            add(code)
            i += length
        else:
            i += 1

    # years
    i = 0
    while i <= n - 4:
        digits = chars[i:i + 4]
        if not any(covered[i:i + 4]) and all("0" <= c <= "9" for c in digits) and 1900 <= int("".join(digits)) <= 2099:
            for k in range(i, i + 4):
                covered[k] = True
            dictionary_bits += pol["year_bits"]
            add("years")
            i += 4
        else:
            i += 1

    # remaining characters, repeats and sequences count less
    rows = pol["sequences"]
    effective = 0.0
    repeat_run = 1
    for i in range(n):
        if covered[i]:
            repeat_run = 1
            continue
        weight = 1.0
        if i > 0 and not covered[i - 1] and chars[i] == chars[i - 1]:
            repeat_run += 1
            weight = 0.25
            if repeat_run >= 3:
                add("repeats")
        else:
            repeat_run = 1
            if i > 1 and not covered[i - 1] and not covered[i - 2]:
                for direction in (1, -1):
                    if _sequential(lower[i - 2], lower[i - 1], direction, rows) and _sequential(lower[i - 1], lower[i], direction, rows):
                        weight = 0.25
                        add("sequences")
                        break
        effective += weight

    bits = effective * math.log2(_pool_size(chars)) + dictionary_bits
    score = sum(1 for threshold in pol["score_bits"] if bits >= threshold)
    if n < pol["min_length"]:
        score = min(score, 1)
    if score < pol["min_score"] and not any(c in feedback for c in ("user_name", "common", "years", "repeats", "sequences")):
        add("longer")
    acceptable = pol["min_length"] <= n <= pol["max_length"] and score >= pol["min_score"]
    return {"score": score, "bits": round(bits, 1), "feedback": feedback, "acceptable": acceptable}
