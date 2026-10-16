"""Deterministic model fixture consumes real imported-script and Browser results."""

import json
import re
import shlex
from dataclasses import dataclass

PROMPT = "Session Browser delegated confidential input"
REPLACEMENT_PROMPT = "Session Browser confidential input after Runner replacement: "
PREFIX = "call_browser_confidential_"
REPLACEMENT_PREFIX = PREFIX + "replacement_"
FINAL = "BROWSER_CONFIDENTIAL_INPUT_VERIFIED"


@dataclass(frozen=True)
class _Page:
    task_id: str
    id: str
    resource_incarnation: str
    title: str


@dataclass(frozen=True)
class _Ref:
    id: str
    observation_id: str
    label: str


@dataclass(frozen=True)
class _Browser:
    page: _Page
    refs: list[_Ref]


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Confidential fixture expected a string field")
    return value


def _decode_browser(text: str) -> _Browser:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Confidential fixture Browser result is invalid")
    page = value.get("page")
    refs = value.get("refs")
    if not isinstance(page, dict) or not isinstance(refs, list):
        raise ValueError("Confidential fixture Browser identity is invalid")
    return _Browser(
        _Page(
            _text(page.get("task_id")),
            _text(page.get("id")),
            _text(page.get("resource_incarnation")),
            _text(page.get("title")),
        ),
        [
            _Ref(
                _text(ref.get("id")),
                _text(ref.get("observation_id")),
                _text(ref.get("label")),
            )
            for ref in refs
            if isinstance(ref, dict)
        ],
    )


@dataclass(frozen=True)
class Observation:
    stage: str
    replacement: bool
    path: str | None
    process_id: str | None
    completed: bool
    stdout: str
    browser: _Browser | None
    rejected: bool


@dataclass(frozen=True)
class Call:
    stage: str
    name: str
    arguments: dict[str, object]


def decode_output(call_id: str | None, value: object) -> Observation | None:
    """Decode consumed tool fields at model-request ingress, preserving no secrets."""
    if call_id is None or not call_id.startswith(PREFIX):
        return None
    replacement = call_id.startswith(REPLACEMENT_PREFIX)
    stage = call_id.removeprefix(REPLACEMENT_PREFIX if replacement else PREFIX)
    text = value
    if isinstance(value, list):
        text = next(
            (part.get("text") for part in value if isinstance(part, dict)), None
        )
    if not isinstance(text, str):
        raise ValueError("Confidential fixture tool output must contain text")
    path = None
    process_id = None
    completed = False
    stdout = ""
    browser = None
    rejected = False
    if stage == "import":
        match = re.search(r" to (/.+) \(", text)
        if match is None:
            raise ValueError("Confidential fixture import has no absolute result path")
        path = match[1]
    elif stage.endswith("encrypt") or "poll" in stage:
        match = re.search(r"^process_id: (\S+)$", text, re.MULTILINE)
        if match is None:
            raise ValueError("Confidential fixture process identity is unavailable")
        process_id = match[1]
        completed = re.search(r"^exit_code: 0$", text, re.MULTILINE) is not None
        if "exit_code:" in text and not completed:
            raise ValueError("Confidential fixture encryption process failed")
        stdout = text.partition("stdout:\n")[2].partition("\n\nstderr:")[0]
    elif stage == "oldfill":
        rejected = "Browser encrypted input is invalid" in text
        if not rejected:
            raise ValueError("Old ciphertext was not rejected by the new process key")
    elif stage in {
        "open",
        "observe",
        "fill",
        "account_fill",
        "unchanged",
        "wait",
        "verify",
    }:
        browser = _decode_browser(text)
    return Observation(
        stage, replacement, path, process_id, completed, stdout, browser, rejected
    )


def _encryption(
    observations: list[Observation], path: str, stage: str, polling: str, variable: str
) -> Call | str:
    processes = [
        item
        for item in observations
        if item.stage == stage or item.stage.startswith(polling)
    ]
    if not processes:
        return Call(
            stage,
            "exec_command",
            {
                "command": "uv run --no-project --script "
                + shlex.quote(path)
                + " --env "
                + variable,
                "yield_time_ms": 1000,
            },
        )
    last = processes[-1]
    if not last.completed:
        return Call(
            f"{polling}{len(processes)}",
            "write_stdin",
            {"process_id": last.process_id, "chars": "", "yield_time_ms": 1000},
        )
    ciphertext = "".join(item.stdout for item in processes).strip()
    if (
        not 64 <= len(ciphertext) <= 5528
        or re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", ciphertext) is None
    ):
        raise ValueError("Confidential fixture requires one bounded ciphertext line")
    return ciphertext


def _fill(
    target: dict[str, object],
    browser: _Browser,
    label: str,
    ciphertext: str,
    stage: str,
) -> Call:
    [ref] = [ref for ref in browser.refs if ref.label == label]
    return Call(
        stage,
        "browser_act",
        {
            **target,
            "action": "fill",
            "ref": ref.id,
            "observation_id": ref.observation_id,
            "encrypted_text": ciphertext,
        },
    )


def next_call(
    observations: list[Observation], *, old_ciphertext: str | None = None
) -> Call | None:
    """Follow actual preparation and both fields; test old-key failure after restart."""
    observations = [
        item
        for item in observations
        if item.replacement == (old_ciphertext is not None)
    ]
    results = {item.stage: item for item in observations}
    if "verify" in results:
        browser = results["verify"].browser
        if browser is None or browser.page.title != "Confidential input verified":
            raise ValueError("Synthetic website did not confirm confidential input")
        return None
    if "skill" not in results:
        return Call(
            "skill",
            "load_skill",
            {"skill_path": "azents://skills/azents/browser/SKILL.md"},
        )
    if "import" not in results:
        return Call(
            "import",
            "import_file",
            {"uri": "azents://skills/azents/browser/scripts/encrypt.py"},
        )
    path = results["import"].path
    if path is None:
        raise ValueError("Imported script path is unavailable")
    if "open" not in results:
        return Call(
            "open",
            "browser_open",
            {"url": "http://127.0.0.1:8766/", "label": "Confidential login"},
        )
    browser = results["open"].browser
    if browser is None:
        raise ValueError("Confidential fixture Browser identity is unavailable")
    target: dict[str, object] = {
        "task_id": browser.page.task_id,
        "page_id": browser.page.id,
        "resource_incarnation": browser.page.resource_incarnation,
    }
    if "observe" not in results:
        return Call("observe", "browser_observe", {**target, "view": "dom"})
    observed = results["observe"].browser
    if observed is None:
        raise ValueError("Confidential fixture observation is unavailable")
    if old_ciphertext is not None:
        if "oldfill" not in results:
            return _fill(
                target, observed, "Confidential password", old_ciphertext, "oldfill"
            )
        if "unchanged" not in results:
            return Call("unchanged", "browser_observe", {**target, "view": "glance"})
        unchanged = results["unchanged"].browser
        if unchanged is None or unchanged.page.title != "Confidential input ready":
            raise ValueError("Rejected ciphertext changed the native website")
    password = _encryption(
        observations, path, "encrypt", "poll", "E2E_BROWSER_PASSWORD"
    )
    if isinstance(password, Call):
        return password
    if "fill" not in results:
        return _fill(target, observed, "Confidential password", password, "fill")
    account = _encryption(
        observations, path, "account_encrypt", "account_poll", "E2E_BROWSER_ACCOUNT"
    )
    if isinstance(account, Call):
        return account
    if "account_fill" not in results:
        return _fill(target, observed, "Confidential account", account, "account_fill")
    if "wait" not in results:
        return Call(
            "wait",
            "browser_act",
            {
                **target,
                "action": "wait",
                "condition": "url",
                "url": "http://127.0.0.1:8766/#verified",
            },
        )
    return Call("verify", "browser_observe", {**target, "view": "glance"})
