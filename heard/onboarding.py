"""First-install onboarding — the ~5 seconds after `heard install` where
we tell the user how to actually use Heard, and the moment we record
that setup is finished. Three surfaces:

  - State: flip the `onboarded` config flag. The daemon suppresses ALL
    event narration until it's true (see `daemon._handle_event`), so
    without this a CLI-only install is permanently silent.
  - CLI: a three-step block so the terminal output isn't just a silent
    "installed".
  - Native banner: a macOS notification via osascript so even users who
    dismissed the terminal see a reminder in their notification center.

No external deps — osascript ships with every Mac.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap


def welcome_block(agent: str) -> str:
    codex_steps = ""
    if agent == "codex":
        codex_steps = """\
          • Codex CLI        open Codex CLI, type /hooks, trust Heard
          • Codex App        keep Heard running; app sessions narrate automatically
"""
    return textwrap.dedent(
        f"""
        ✓ Installed for {agent}.

        Next steps:
          • Silence hotkey    ⌘⇧.
          • Menu bar          heard ui
          • Try Jarvis voice  heard preset jarvis
          • Voice + brain     heard config set elevenlabs_api_key <key>
                              heard config set anthropic_api_key <key>
{codex_steps}

        First narration downloads the voice model (~350 MB, one-time) and
        macOS will ask once for Accessibility access — that's the hotkey.
        """
    ).strip()


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def notify(title: str, subtitle: str = "", message: str = "") -> bool:
    """Post a native macOS notification. Returns False on any failure —
    callers should treat this as best-effort only."""
    if sys.platform != "darwin":
        return False
    if not shutil.which("osascript"):
        return False
    parts = [f'display notification "{_escape(message or " ")}"', f'with title "{_escape(title)}"']
    if subtitle:
        parts.append(f'subtitle "{_escape(subtitle)}"')
    script = " ".join(parts)
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def hook_installed() -> bool:
    """True when ANY agent adapter has its hook wired into that agent's
    settings file — the CLI's durable proof that setup really happened.

    Best-effort per adapter: a hand-mangled `~/.claude/settings.json`
    must not take the daemon's narration path down, so an adapter that
    raises simply doesn't get a vote.
    """
    from heard.adapters import ADAPTERS  # noqa: PLC0415 — keeps daemon import cheap

    for adapter in ADAPTERS.values():
        try:
            if adapter.is_installed():
                return True
        except Exception:
            continue
    return False


def _in_app_bundle() -> bool:
    """True when we're running inside the py2app `Heard.app` bundle.

    Same shape check as `adapters.build_hook_command`. Inside the
    bundle the first-launch wizard owns the `onboarded` flag, so the
    hook-based self-heal below must stay out of its way.
    """
    exe = sys.executable
    return "/Contents/MacOS/" in exe and ".app/" in exe


def mark_onboarded() -> bool:
    """Record that setup is finished. Returns True iff the flag actually
    flipped, so callers can log a one-time heal instead of re-writing
    config on every call. Never raises — a config that can't be written
    is worth a silent no-op, not a failed `heard install`."""
    from heard import config  # noqa: PLC0415 — avoids an import cycle via cli

    try:
        if config.load().get("onboarded"):
            return False
        config.set_value("onboarded", True)
        return True
    except Exception:
        return False


def resolve_onboarded(cfg: dict) -> tuple[bool, bool]:
    """Decide whether narration is allowed yet, with self-heal.

    Returns ``(onboarded, should_heal)`` — same shape as the menu bar's
    `ui._resolve_onboarded`, which solves the same drift problem for the
    GUI. The daemon gates all event narration on this.

    Why a fallback at all: `onboarded` is set by exactly two things —
    the GUI first-launch wizard and `heard install` (via
    `after_install`). If the flag drifts back to False on a machine that
    is plainly already set up — a wiped config dir, the corrupt-config
    auto-reset in `config._read_yaml`, an upgrade from a build predating
    the flag — a CLI-only install goes permanently silent with no
    visible cause, because nothing re-runs `heard install`. An installed
    hook is unambiguous evidence the user finished setup, so we treat it
    as onboarded and flag the stale value for healing.

    Inside the .app bundle we deliberately do NOT apply the fallback:
    there the wizard is the authority, and its whole point is to stay
    quiet while it's on screen — including the step where it wires up
    the very hook we'd otherwise read as "done".
    """
    if cfg.get("onboarded"):
        return True, False
    if _in_app_bundle():
        return False, False
    if hook_installed():
        return True, True  # CLI install is finished; persist the healed flag
    return False, False


def after_install(agent: str) -> None:
    """Run all three surfaces right after a successful
    `heard install <agent>`.

    Marking onboarded is the load-bearing one: wiring up an agent IS the
    CLI's "I finished setup" signal (the GUI equivalent is closing the
    wizard). Without it the daemon drops every hook event it receives.
    """
    mark_onboarded()
    print()
    print(welcome_block(agent))
    print()
    notify(
        title="Heard is ready",
        subtitle="⌘⇧. to silence · heard ui for menu bar",
        message=f"Next {agent} response will be narrated.",
    )
