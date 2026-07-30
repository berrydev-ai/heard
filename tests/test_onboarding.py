from unittest.mock import MagicMock, patch

from heard import onboarding


def test_welcome_block_mentions_agent_and_hotkey():
    out = onboarding.welcome_block("claude-code")
    assert "claude-code" in out
    assert "⌘⇧." in out
    assert "heard ui" in out
    assert "heard preset jarvis" in out


def test_welcome_block_points_keys_at_config_set():
    """Nothing in the package reads a .env, and the daemon is usually
    spawned by a hook rather than from the user's shell — so the key
    advice has to be `heard config set`, not an env var. ElevenLabs is
    config-only regardless (see Daemon._make_tts)."""
    out = onboarding.welcome_block("claude-code")
    assert "heard config set anthropic_api_key" in out
    assert "heard config set elevenlabs_api_key" in out
    assert "ANTHROPIC_API_KEY" not in out


def test_escape_preserves_safe_chars():
    assert onboarding._escape("hello world") == "hello world"


def test_escape_quotes_and_backslashes():
    # quotes get escaped for osascript inclusion
    assert onboarding._escape('say "hi"') == 'say \\"hi\\"'
    assert onboarding._escape("path\\sub") == "path\\\\sub"


def test_escape_flattens_newlines():
    assert onboarding._escape("line1\nline2") == "line1 line2"


def test_notify_returns_false_off_darwin(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert onboarding.notify("t", "s", "m") is False


def test_notify_calls_osascript_on_darwin(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(onboarding, "_escape", lambda s: s)
    with patch("shutil.which", return_value="/usr/bin/osascript"):
        fake_run = MagicMock()
        with patch("subprocess.run", fake_run):
            ok = onboarding.notify("Heard ready", subtitle="⌘⇧.", message="go")
    assert ok is True
    fake_run.assert_called_once()
    args = fake_run.call_args[0][0]
    assert args[0] == "osascript"
    assert args[1] == "-e"
    assert "Heard ready" in args[2]
    assert "⌘⇧." in args[2]


def test_notify_returns_false_when_osascript_missing(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    with patch("shutil.which", return_value=None):
        assert onboarding.notify("t") is False


def test_after_install_prints_welcome_and_notifies(capsys, monkeypatch):
    called = {}

    def fake_notify(title, subtitle="", message=""):
        called["title"] = title
        return True

    monkeypatch.setattr(onboarding, "notify", fake_notify)
    onboarding.after_install("codex")
    out = capsys.readouterr().out
    assert "codex" in out
    assert "⌘⇧." in out
    assert "Codex CLI" in out
    assert "Codex App" in out
    assert called["title"] == "Heard is ready"


# --- onboarded state: the CLI's "setup is finished" signal ---------------


def test_after_install_marks_onboarded(monkeypatch):
    """The regression this whole module exists for: on a CLI-only
    install nothing ever opens the GUI wizard, so `heard install` has to
    be what flips `onboarded`. Without it the daemon drops every hook
    event it receives and Heard is permanently, silently dead."""
    from heard import config

    monkeypatch.setattr(onboarding, "notify", lambda *a, **kw: True)
    assert config.load().get("onboarded") is False

    onboarding.after_install("claude-code")

    assert config.load().get("onboarded") is True


def test_mark_onboarded_reports_whether_it_changed():
    from heard import config

    assert onboarding.mark_onboarded() is True   # False → True
    assert config.load().get("onboarded") is True
    assert onboarding.mark_onboarded() is False  # already set; no re-write


def test_mark_onboarded_survives_unwritable_config(monkeypatch):
    """A config we can't persist must not turn `heard install` into a
    traceback — the hook is already wired up at that point."""
    def _boom(*_a, **_kw):
        raise OSError("read-only file system")

    monkeypatch.setattr("heard.config.set_value", _boom)
    assert onboarding.mark_onboarded() is False


def test_hook_installed_true_when_an_adapter_says_so(monkeypatch):
    monkeypatch.setattr("heard.adapters.claude_code.is_installed", lambda: False)
    monkeypatch.setattr("heard.adapters.codex.is_installed", lambda: True)
    assert onboarding.hook_installed() is True


def test_hook_installed_false_when_no_adapter_has_a_hook(monkeypatch):
    monkeypatch.setattr("heard.adapters.claude_code.is_installed", lambda: False)
    monkeypatch.setattr("heard.adapters.codex.is_installed", lambda: False)
    assert onboarding.hook_installed() is False


def test_hook_installed_ignores_a_raising_adapter(monkeypatch):
    """A hand-mangled ~/.claude/settings.json must not take the daemon's
    narration path down — the broken adapter just doesn't get a vote."""
    def _boom():
        raise ValueError("malformed settings.json")

    monkeypatch.setattr("heard.adapters.claude_code.is_installed", _boom)
    monkeypatch.setattr("heard.adapters.codex.is_installed", lambda: True)
    assert onboarding.hook_installed() is True


# --- resolve_onboarded: the daemon's gate + self-heal --------------------


def _explode():
    raise AssertionError("hook_installed must not be consulted when the flag is set")


def test_resolve_trusts_the_flag_without_touching_hooks(monkeypatch):
    monkeypatch.setattr(onboarding, "hook_installed", _explode)
    assert onboarding.resolve_onboarded({"onboarded": True}) == (True, False)


def test_resolve_heals_a_drifted_flag_when_a_hook_is_installed(monkeypatch):
    """A config reset (or the corrupt-config auto-reset in
    `config._read_yaml`) drops `onboarded` back to False on a machine
    that is plainly already set up. Nothing re-runs `heard install`, so
    without this the fork goes silent again with no visible cause."""
    monkeypatch.setattr(onboarding, "hook_installed", lambda: True)
    monkeypatch.setattr(onboarding, "_in_app_bundle", lambda: False)
    assert onboarding.resolve_onboarded({"onboarded": False}) == (True, True)


def test_resolve_keeps_a_genuine_first_timer_gated(monkeypatch):
    monkeypatch.setattr(onboarding, "hook_installed", lambda: False)
    monkeypatch.setattr(onboarding, "_in_app_bundle", lambda: False)
    assert onboarding.resolve_onboarded({}) == (False, False)


def test_resolve_leaves_the_gui_wizard_in_charge_inside_the_app(monkeypatch):
    """Inside Heard.app the wizard owns the flag, and its whole point is
    staying quiet while it's on screen — including the step where it
    wires up the very hook we'd otherwise read as 'setup done'."""
    monkeypatch.setattr(onboarding, "hook_installed", lambda: True)
    monkeypatch.setattr(onboarding, "_in_app_bundle", lambda: True)
    assert onboarding.resolve_onboarded({"onboarded": False}) == (False, False)


def test_in_app_bundle_detects_the_py2app_launcher(monkeypatch):
    monkeypatch.setattr(
        "sys.executable", "/Applications/Heard.app/Contents/MacOS/Heard"
    )
    assert onboarding._in_app_bundle() is True


def test_in_app_bundle_false_for_a_normal_interpreter(monkeypatch):
    monkeypatch.setattr("sys.executable", "/Users/x/heard/.venv/bin/python3")
    assert onboarding._in_app_bundle() is False
