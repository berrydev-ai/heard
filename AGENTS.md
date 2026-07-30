# Heard — contributor & agent guide

A macOS voice companion that narrates Claude Code / Codex / arbitrary CLI
agents. py2app menu-bar bundle + CLI. Apache 2.0.
[heard.dev](https://heard.dev) · [Releases](https://github.com/heardlabs/heard/releases)

This file is the guide for contributors and for coding agents opened in
this repo (Claude Code auto-reads it via `CLAUDE.md`). Keep it current
when the architecture shifts. For setup, the test gate, and the PR flow,
see `CONTRIBUTING.md`.

---

## Process model

Heard runs two ways, and the difference matters for setup:

- **App install** — the menu-bar app (`Heard.app`) runs the daemon as an
  in-process thread. This is what most of this doc describes.
- **CLI-only install** (`pip install -e .` + `heard install <agent>`, no
  `.app` built) — there is no menu bar and no first-launch wizard. The
  daemon is auto-spawned by the first hook event and supervised by
  nothing. Everything works, but **every GUI-gated path has to have a
  CLI equivalent**; see [CLI-only setup](#cli-only-setup) for the two
  that bite.

Hooks installed by Claude Code / Codex are spawned as short-lived
`python -m heard.hook <agent>` subprocesses. They read the hook payload
from stdin, send a JSON message over a Unix-domain socket to the daemon,
and exit.

```
CC tool call
  ↓
~/.claude/settings.json hook → python -m heard.hook claude-code
  ↓ stdin: {"hook_event_name": "PreToolUse", ...}
heard.client.send_event() → Unix socket
  ↓
Heard.app (daemon thread) — _handle_event routes by kind:
  ├─ tool_pre / tool_post  → fast-path templates (no LLM)   → speech queue
  ├─ prose / finals        → harness (the brain)            → speech queue
  └─ harness punts (None)  → no-LLM floor (canned/template) → speech queue
  ↓
afplay → history.append (after successful play)
```

The **harness brain is the mandatory narration path** for prose and
finals. There are exactly three lanes:

1. **Brain** (`harness.narrate`) — prose + finals. One Haiku call with
   access to the persona, the Agent State scoreboard, and Working Memory.
2. **Fast-path templates** — tool actions ("Editing auth.py"); never the
   brain (latency/cost). Cheap, no LLM.
3. **No-LLM floor** (`Daemon._floor_text`) — fires only when the brain
   punts (LLM unreachable: daily cap, outage, no provider). Tools keep
   their clean template; a **final** is read as-is if short, else swapped
   for a bounded lead of the message prefixed with the project. This
   floor — not any legacy path — is the only fallback. The floor (and the
   local Kokoro TTS option) is what keeps Heard from going silent, which
   for an ambient tool reads as "broken."

## CLI-only setup

Two things are wired to the GUI by default. Both have CLI equivalents
now — if you add a third, give it one in the same change.

### 1. The onboarding gate (`onboarded`)

`daemon._handle_event` drops **every** hook event before narration until
setup is marked finished:

```python
onboarded, heal_onboarded = onboarding.resolve_onboarded(cfg)
if not onboarded:
    _log("event_drop", kind=kind, tag=tag, reason="not_onboarded")
    return
```

The flag defaults to False and has two writers:

- **GUI** — the first-launch wizard, via `home_window._mark_onboarded`.
- **CLI** — `heard install <agent>`, via `onboarding.after_install` →
  `mark_onboarded()`. Wiring up an agent *is* the CLI's "setup finished"
  signal; the GUI equivalent is closing the wizard.

`onboarding.resolve_onboarded(cfg)` returns `(onboarded, should_heal)`
and adds a **self-heal**: outside the `.app` bundle, an installed agent
hook counts as proof setup happened, so a flag that drifted false
(wiped config, the corrupt-config auto-reset in `config._read_yaml`, an
upgrade from a pre-flag build) doesn't leave a CLI-only install
permanently and invisibly mute. Inside the bundle the fallback is
deliberately skipped — there the wizard is the authority, and it wires
up the hook *during* the flow we'd otherwise read as "done". The GUI has
its own parallel resolver, `ui._resolve_onboarded`, on the same shape.

Debugging a "Heard is installed but never speaks" report starts here:
`heard config get onboarded`, then grep the daemon log for
`reason=not_onboarded`.

### 2. Keys (no `.env`)

**Nothing in the package loads a `.env` file, and it should stay that
way.** `.env.example` documents the env-var names only. Reasons not to
add a loader:

- The daemon is a **single long-lived process shared by every project**.
  It has no per-project environment, so one repo's `.env` would arm the
  keys used to narrate every other repo's sessions.
- It's normally **auto-spawned by a hook**, so it inherits the agent's
  environment, not the shell you exported into — which `.env` file it
  picked up would depend on which project happened to fire first.
- `elevenlabs_api_key` isn't read from the environment anywhere
  (`Daemon._make_tts` is config-only), so a loader would need new
  plumbing rather than just a parser.
- Auto-slurping secrets out of a cloned repo is a bad default.

`heard config set <key> <value>` is the path. It writes to the user
config dir, which the daemon re-reads via `config.load()` on **every
event** — so a key takes effect with no daemon restart, whatever
launched it. Config also wins over env in `persona._anthropic_key`.

## Module map

This table is the canonical "what's in the codebase" reference. When you
add a module or meaningfully change one's role, update the row in the
same change — a drifted table is worse than none.

| File | Responsibility |
|---|---|
| `heard/daemon.py` | Long-running daemon. Owns the speech queue, hotkey listener, audio monitor, multi-agent router, history append, periodic digest timer. Narration routing (`_handle_event`): observe first (Agent/Working/Project Memory), then the onboarding gate (`onboarding.resolve_onboarded` — drops everything until setup is finished), then tool events → fast-path templates; prose/finals → `harness.narrate`; harness punt → `_floor_text` (the no-LLM floor). Duplicate suppression drops identical raw events (`_is_duplicate_event`) and consecutive identical tool lines (`_is_duplicate_tool_line`). Socket commands dispatched in `_handle()`: `ping`, `status`, `pin`, `unpin`, `reload`, `stop`, `mute`, `unmute`, `mute_session` / `unmute_session`, `feedback`, `report_defect`, `ask`, `recap`, `event`, `utterance`, `inject`, `open_home`, `refresh_account`, `request_accessibility`, `resume_intent`, `voice_hold` / `voice_release`. |
| `heard/client.py` | Hook-side helpers: spawn the daemon if needed, send events / status / pin commands over the Unix socket. |
| `heard/hook.py` | Entry-point invoked by the agent's hook command. Routes to `client.handle_cc_*` / `client.handle_codex_*`. |
| `heard/wrapper.py` | `heard run <cmd> [args...]` — universal terminal wrapper. Spawns an agent, tees its stdout, and synthesizes events for agents without a native hook surface. |
| `heard/adapters/claude_code.py` + `codex.py` | Install / uninstall the hook into `~/.claude/settings.json` and `~/.codex/hooks.json`. PYTHONHOME-wrapped command for the .app bundle case. |
| `heard/codex_app.py` | Codex **Desktop** observer — app-chat tool calls never run the user hook file, so `CodexAppObserver` tails `~/.codex/sessions/**/*.jsonl` (originator `Codex Desktop` only) on a poll thread and `event_from_record` converts each JSONL record into the same daemon event shape the hook path emits. Byte offsets persist in `codex_app_observer.json`; new files start at EOF so enabling it never replays history. |
| `heard/multi_agent.py` | Solo / Swarm / Pinned router. Decides per-event: speak / drop / defer-to-digest. Project-keyed channel scheduler batches background-agent activity into narrative summaries, with template fallback. `format_digest`, `drain_session_summary`, `pin`/`unpin`, `list_active`. |
| `heard/session.py` | In-memory per-session state, keyed by the agent's `session_id`. `touch` upserts (cwd + derived `repo_name` + `last_seen`); `record_tool_event`/`tool_density` feed the burst threshold; `note_failure`/`note_topic` carry the recent-failure count and last-narrated breadcrumb. Idle sessions are evicted. |
| `heard/agent_state.py` | **Layer 2 — Agent State (the "scoreboard").** Per-agent record with facts (current_tool, files_touched, error_count, …) + cheap heuristic hints. Boundary rule: never an LLM, never a decision — if a Python function can compute it from raw events, it's Layer 2. |
| `heard/working_memory.py` | **Layer 3 — Working Memory.** Short rolling prose summary of "what's going on right now." Hot-path `observe(event)` appends to a ring buffer; a background compressor thread periodically compresses. Stale-tolerant: a failed compression never bashes the last good summary. |
| `heard/project_memory.py` | **Layer 4 — Project Memory.** One append-only JSONL per project (`project_memory/<sha256(cwd)[:16]>.jsonl`, 50 MB rotation) written on EVERY event — no LLM on the write path, best-effort so a failed write never blocks speech. Trims `neutral` to 800 chars and strips blob ctx keys (`stdout`, `file_content`, …). Read side is the Q&A surface: `iter_recent` (tail-only) feeds `answer(question)` (`heard ask`), `recap`, and `recap_turn`. Strictly local — records hold real paths, nothing leaves the machine. |
| `heard/harness.py` | **Layer 5 — the mandatory narration brain.** `narrate(event, cfg, persona, agent_states, working_memory)` builds a cached system block (persona + shared rules + instruction block) + a dynamic user message (rolling summary + ranked active-agent snapshot + current event), dispatches via `persona.call_with_prompt`, and returns a `HarnessDecision`: `None` → daemon's no-LLM floor; `speak=False` → chose silence; `speak=True` → daemon enqueues the text. Prompt assembly is pure so it's unit-testable without the LLM. |
| `heard/preferences.py` + `heard/preferences_schema.yaml` | **Layer 6 — personalization substrate.** Bounded slot vocabulary in the schema; `resolve(cwd)` applies the overlay stack (schema defaults → `$CONFIG_DIR/preferences.yaml` → nearest `.heard.yaml` `preferences:` key) and always returns every slot. `validate` enforces type + range only (raises `ValidationError`); the resolver drops bad entries instead of raising, so broken prefs can never block narration. `to_prompt_text` renders only non-default slots (byte-stable cached prefix otherwise) for the harness system block. `set_value`/`remove_value`/`reset_all` + `append_history` back `heard preferences …`. No LLM, no daemon calls. |
| `heard/config.py` | Layered config resolver — `DEFAULTS` (every flag lives here, heavily commented) → global `$CONFIG_DIR/config.yaml` → nearest per-project `.heard.yaml`, all in one `load(cwd=…)`. Owns the path constants (`CONFIG_DIR`, `DATA_DIR`, `SOCKET_PATH`, `LOG_PATH`, `PID_PATH`, `MODELS_DIR`). `save` writes only keys in `DEFAULTS` whose value differs, so explicit choices survive and preset pollution self-cleans. A corrupt global YAML is renamed `.broken-<ts>` + notified rather than crashing startup; a corrupt project file is just ignored. `project_label(cwd)` reads the spoken-only `label:` (never sent to analytics). |
| `heard/profile.py` + `heard/profiles/*.yaml` | Verbosity profiles (quiet / brief / normal / verbose). Five dimensions per profile. User dir overrides bundled. |
| `heard/verbosity.py` | Three-way classifier for the fast path: `classify_pre` → `speak/drop/digest`. Failures + questions always pierce. |
| `heard/persona.py` | Persona load + LLM dispatch. `_SHARED_NARRATION_RULES` is the cross-persona framing. `call_with_prompt(...)` is the live entry point the harness brain and burst digests dispatch through (prompt caching + observability). BYOK Anthropic → managed proxy → `claude -p` CLI ladder. Model: `HAIKU_MODEL` is the PINNED checkpoint `claude-haiku-4-5-20251001` (the bare alias would move under us); `brain_model` overrides it on the BYOK path only. |
| `heard/providers.py` | Provider abstraction for the narration LLM (partially-finished extraction). |
| `heard/personas/*.md` | Bundled personas (aria, friday, jarvis, atlas). YAML frontmatter (voice/speed/verbosity/…) + Markdown body (Haiku system prompt). |
| `heard/templates.py` | Per-tool narration templates. `_bash_tag_and_text` extracts intent from shell verbs (grep → search, ls → list, …). |
| `heard/markdown.py` | Strips Markdown before TTS. Handles fenced/indented code, blockquotes, tables, links, emphasis. |
| `heard/spoken.py` | Per-session dedup of already-narrated assistant text. `flock`'d read-modify-write on `<session>.json`. |
| `heard/history.py` | Spoken-history JSONL log. Append-only, checkpoint-based pruning. Each utterance record carries an `id`; preference feedback lands as sibling `type="feedback"` records. |
| `heard/defects.py` | Defect-report sidecar (`defect_reports.jsonl`). Closed category enum; each record carries `tech_context`. Local-only, no network. |
| `heard/tts/elevenlabs.py` + `tts/kokoro.py` + `tts/managed.py` + `tts/null.py` | TTS backends. Selector order in `Daemon._make_tts`: BYOK `elevenlabs_api_key` → `ElevenLabsTTS`, but GATED — a key only wins if the account is `byok_enabled` or the managed path isn't usable (no token / expired / capped today), so an active Pro can't sidestep the voices it pays for; else usable `heard_token` → `ManagedTTS` (proxies api.heard.dev); else if the Kokoro model is already downloaded → `KokoroTTS`; else `NullTTS` (silent + a one-time "add a voice" nudge). Kokoro is opt-in only — never auto-downloaded, and lazily imported so cloud users never load onnxruntime. |
| `heard/url_scheme.py` | `heard://` Apple-Event handler. Only answers `heard://auth?code=…` — the tail of the web sign-in handoff. `CFBundleURLTypes` lives in `packaging/setup.py`. |
| `heard/heard_api.py` | Client for `api.heard.dev`. Auth endpoints (install-code → bearer, refresh, signout) + plan/usage status. |
| `heard/analytics.py` | PostHog product analytics, opt-OUT via the `product_analytics` flag — when it's off NOTHING fires (no Tier-1 carve-out). `capture(event, props, set_person=…)` POSTs raw HTTPS on a daemon thread (no SDK in the py2app bundle) and swallows every failure; `identify` aliases the anonymous `install_id()` to the signed-in user so pre-signin events back-fill; `sampled(rate)` gates high-frequency events against the quota; `mark_first_launch_if_new` drives `app_first_launched`. Anonymous + categorical only — no narration text, no paths, no file names; CI runs and the public ingest key are handled here. |
| `heard/audio_monitor.py` | CoreAudio polling for "any app capturing the mic" → auto-silence. Debounced to filter notification-class mic blips. |
| `heard/hotkey.py` + `accessibility.py` | Cocoa `NSEvent` global monitor (not pynput — only the config's binding STRINGS stay pynput-style) carrying both combos: `hotkey_pause` (`<shift>+<alt>+.`) and `hotkey_continue` (`<shift>+<alt>+,`). Daemon polls Accessibility trust and re-inits on the False→True transition. |
| `heard/push_to_talk.py` | Hold-to-talk trigger. `start(sock_path, keycode)` adds a global flagsChanged monitor for held RIGHT ⌘ (keycode 54) and fire-and-forget pokes `start` / `stop` at the voice service's socket — observe-only, so the key still behaves normally elsewhere. Lives in the daemon because only the daemon has Accessibility trust. Inert with no socket path; keep the returned monitor referenced or it's GC'd. |
| `heard/ptt_indicator.py` | The "Listening" HUD shown while the hold-to-talk key is down. `show()` / `hide()` on a borderless, click-through, all-spaces frosted pill with a pulsing dot, pinned to the primary display. Built once and reused; AppKit imported lazily; main-thread only; every failure swallowed so UI can never break the key. |
| `heard/voice_service.py` | **The open-core seam.** `VoiceServiceSupervisor` runs Heard Power's `serve` as a plain SUBPROCESS named by `voice_service_cmd` and talks to it only over `~/.heard_power.sock` — OSS never imports `heard_power`, so an empty cmd simply means no voice input. Idempotent `sync(should_run)` starts/stops it; a keepalive thread relaunches on exit with capped backoff, and a ping/pong watchdog kills a serve that is alive but has a WEDGED accept loop. Repeated fast crashes fire `on_unhealthy` (with the log tail) instead of failing silently. Never raises into the narration path. |
| `heard/ui.py` | rumps menu bar (`heard ui`), a separate process from the daemon — discoverability and quick toggles, never a required control plane. Account row, Pause/Continue, Active agents (+ pin/unpin), Persona / Speed / **Mode** submenus (Mode replaced the old Verbosity submenus — verbosity now lives under Settings → Voice), Voice input / Pair phone, API keys, Options, update item, "Settings…" → `home_window.show_home()`, and "Report a problem…" (the only user-facing feedback surface). |
| `heard/settings_widgets.py` | Reusable AppKit widget primitives for the native windows: theme constants (offwhite / light / dark), the layer-drawn `NSView` / `NSButton` / `NSTextFieldCell` subclasses behind the non-system look, and the `_label` / `_button` / `_text_field` / `_checkbox` / `_popup` / `_segmented` + row / card composers. Pure UI — no daemon, config, or persona imports. |
| `heard/home_window.py` + `heard/onboarding.html` | The persistent Heard window: one native `NSWindow` hosting `onboarding.html` in a WKWebView (not a browser). Setup-incomplete → onboarding as a re-openable task checklist; done → Home (Mission Control / Transcript / Settings). Replaced the old native `_OnboardingController` wizard. `_mark_onboarded()` is the GUI writer of the `onboarded` flag. Contract: the page posts `{action, …}` to `messageHandlers.heard` → an `_act_*` method (sign-in, connect agent, set voice/mode/speed/verbosity/keys, preview line, start Power trial, grant Accessibility, upgrade); native pushes `_current_state()` back via `window.__heard.setState({…})`. AppKit/WebKit imports are lazy so CLI paths don't pull WebKit. |
| `heard/onboarding.py` | **CLI-side onboarding.** `after_install(agent)` runs on the `heard install` path: marks `onboarded`, prints the next-steps block, posts an osascript banner. `resolve_onboarded(cfg)` is the daemon's narration gate + hook-based self-heal; `hook_installed()` aggregates the adapters' `is_installed()`. See [CLI-only setup](#cli-only-setup). |
| `heard/prompt_window.py` | Native modal-dialog helpers (choice / text / defect-report). AppKit imports are lazy so importing on a CLI path doesn't pull AppKit. Main-thread only. |
| `heard/notify.py` | User-visible macOS notifications via `osascript`. `notify(title, body, kind=…)` dedups per `(kind, body)` for 60s. |
| `heard/service.py` | macOS LaunchAgent integration. Writes `~/Library/LaunchAgents/dev.heard.daemon.plist` and runs `launchctl load/unload`. |
| `heard/updater.py` | In-app updater. Polls GitHub releases; resolves the running version from `Info.plist` as a backstop for the string in `heard/__init__.py`. |
| `heard/tune.py` | `heard tune` — interactive walk through voice / persona / verbosity for CLI users. |
| `heard/cli.py` | Typer CLI. Heard's product surface is the menu bar, not the terminal — most commands are `hidden=True` (functional, just absent from `heard --help`). Visible in `--help`: `install`, `uninstall`, `run`, `service install/uninstall`. |
| `packaging/setup.py` + `packaging/build-app.sh` + `packaging/app_entry.py` | py2app build. Bundles certifi / urllib3 / libssl etc. (the frozen Python's @rpath quirks). `app_entry.py` sets `SSL_CERT_FILE` before any HTTPS-using import. |

## Hot-patch workflow

**CLI-only install.** An editable install (`pip install -e .`) already
points at your working tree, so there's nothing to sync — just bounce
the daemon and let the next hook event respawn it:

```bash
heard stop
```

Tail `~/Library/Application Support/heard/daemon.log` to watch it come
back on the next agent event.

**App install.** For Python-only changes (no native deps), iterate
without rebuilding the .app by syncing the package into the installed
bundle:

```bash
# NOTE: source is the PACKAGE dir (~/path/to/heard/heard/heard/), not the
# repo root. Syncing the repo root here copies docs / tests / .git over
# the bundle and — with --delete — replaces the package with non-package
# files, breaking the app. Three `heard` segments in the source path.
rsync -a --delete ~/path/to/heard/heard/heard/ /Applications/Heard.app/Contents/Resources/lib/python3.13/heard/
killall Heard 2>/dev/null
sleep 1
rm -f ~/Library/Application\ Support/heard/daemon.sock ~/Library/Application\ Support/heard/daemon.pid
open /Applications/Heard.app
```

The daemon is back in ~3s. Tail `~/Library/Application Support/heard/daemon.log`
to verify it came up cleanly.

## Coding conventions

- **`encoding="utf-8"` on every `open()` / `read_text()` / `write_text()`.**
  The frozen Python in the .app bundle defaults to ASCII; non-ASCII bytes
  (em-dashes in persona MDs, transcript Unicode) crash without it.
- **flock'd read-modify-write** for any per-session state (spoken hashes,
  history prune). Concurrent CC + Codex sessions race otherwise.
- **Structured `_log` lines in `daemon.py`.** Every event prints one
  `t=... ev=<event> key=value` line to the daemon log (10MB rotation).
  Keep it grepable — no prose.
- **Notifications via `heard.notify.notify(title, body, kind=...)`.**
  Dedup'd 60s per kind; use a stable kind to avoid spam.
- **Backwards-compat for config keys.** Legacy values map to current ones
  at load time (e.g. `verbosity: low/high` → `quiet/verbose`). Don't
  break existing `config.yaml` without a migration path.
- **No `try: ... except Exception: pass` around new code** unless the
  alternative is a daemon crash. Surface errors via `_record_error` +
  `notify`.
- Lint with `ruff`. B023 (closure capturing a loop var) is the most
  common miss — bind via default args.

## Common file edits

- **Persona tone** → `heard/personas/<name>.md` (Haiku system prompt body)
- **Cross-persona framing** → `_SHARED_NARRATION_RULES` in `heard/persona.py`
- **Verbosity behaviour** → `heard/profiles/<name>.yaml` (5 dimensions)
- **Per-tool narration templates** → `heard/templates.py`
- **Multi-agent decision logic** → `heard/multi_agent.py`

## Running tests

See `CONTRIBUTING.md` for full setup. The gate is:

```bash
ruff check heard/ tests/
pytest -q
```

Prompt-assembly helpers in `harness.py` are pure, so the brain is
unit-testable without hitting the LLM.

## Diagnostic files

In `~/Library/Application Support/heard/`:

- `daemon.log` — structured event stream (10MB rotation).
- `history.jsonl` — every utterance Heard spoke; each record has a
  unique `id`, with sibling `type="feedback"` records referencing them.
- `defect_reports.jsonl` — local-only defect-report sidecar.
- `config.yaml` — current settings. Read/write it with
  `heard config get` / `heard config set <key> <value>` (or the
  menu-bar settings UI on an app install). Only keys whose values
  differ from `config.DEFAULTS` are persisted.
