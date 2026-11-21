import json
import os
import random
import shutil
import subprocess

import pytest

from password_strength import POLICY_PATH, evaluate, policy

JS_PATH = os.path.join(os.path.dirname(POLICY_PATH), "password_strength.js")


@pytest.mark.parametrize("password, acceptable, feedback", [
    ("", False, "too_short"),
    ("password", False, "common"),
    ("Password1!", False, "common"),
    ("P@ssw0rd2024!", False, "years"),
    ("sunshine2024", False, "common"),
    ("aq-demo-2024", False, "common"),        # default password of the mock system
    ("admin12345", False, "user_name"),
    ("nimda-1234", False, "user_name"),       # reversed user name
    ("1234567890", False, "sequences"),
    ("qwertyuiop12", False, "sequences"),
    ("aaaaaaaaaaaa", False, "repeats"),
    ("Xk9#mP2q", False, "too_short"),         # random, but too short
    ("kdjfurieow", True, None),
    ("Tr0ub4dor&3", True, None),
    ("correct horse battery staple", True, None),
    ("zVb7-Qe2-Kpw9", True, None),
])
def test_examples(password, acceptable, feedback):
    result = evaluate(password, ["admin"])
    assert result["acceptable"] is acceptable, result
    if feedback:
        assert feedback in result["feedback"], result
    assert 0 <= result["score"] <= 4


def test_scores_increase_with_the_length_of_random_passwords():
    rng = random.Random(1)
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789-_!#"
    scores = [evaluate("".join(rng.choice(alphabet) for _ in range(n)))["score"] for n in (6, 9, 12, 16)]
    assert scores == sorted(scores) and scores[-1] == 4


def test_too_long():
    result = evaluate("x7#Kq" * 30)
    assert not result["acceptable"] and "too_long" in result["feedback"]


def _cases():
    rng = random.Random(7)
    pieces = policy()["words"][:60] + ["admin", "nimda", "1990", "2024", "abc", "cba", "321", "qwe", "zzz", "@", "0", "1", "$",
                                       "ß", "é", "Ω", "😀", " ", "-", "Z", "Q", "xx", "9"]
    cases = [""]
    for _ in range(400):
        cases.append("".join(rng.choice(pieces) if rng.random() < 0.4 else rng.choice("aZ9#qé😀-1@0$")
                             for _ in range(rng.randint(1, 9))))
    return cases


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_same_results_as_the_browser():
    cases = _cases()
    script = (f"const {{evaluatePassword}} = require({json.dumps(JS_PATH)});"
              f"const policy = require({json.dumps(POLICY_PATH)});"
              "const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
              "process.stdout.write(JSON.stringify(cases.map(c => evaluatePassword(c, ['admin'], policy))));")
    output = subprocess.run(["node", "-e", script], input=json.dumps(cases), capture_output=True, text=True, check=True).stdout
    for password, js in zip(cases, json.loads(output)):
        py = evaluate(password, ["admin"])
        assert (py["score"], py["feedback"], py["acceptable"]) == (js["score"], js["feedback"], js["acceptable"]), password
        assert abs(py["bits"] - js["bits"]) < 0.11, password
