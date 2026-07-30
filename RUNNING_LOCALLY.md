# Running Heard locally (CLI-only fork)

**This fork has no app.** Upstream Heard ships a macOS menu-bar app
(`Heard.app`) plus a CLI. Here we run **only the CLI and its background
daemon** — nothing gets built, packaged, or dragged into `/Applications`.

That one difference is the source of every gotcha below, because parts of
the upstream code quietly assume the app is there to do setup for you.

> **Read this before `AGENTS.md` or `README.md`.** Those still describe
> the app-centric flow. See [What to ignore upstream](#what-to-ignore-in-the-upstream-docs).

---

## The short version

Wire up an agent, then set two keys:

```bash
.venv/bin/heard install claude-code
.venv/bin/heard config set anthropic_api_key sk-ant-YOUR-KEY
.venv/bin/heard config set elevenlabs_api_key YOUR-KEY
```

`heard install` is the load-bearing one — it's what tells Heard setup is
finished, so the daemon will actually narrate. The keys buy you a brain
and a voice.

Everything else — the daemon, the hooks, autostart — takes care of itself.

---

## How the pieces fit

Think of it like a **radio station**. Your coding agent is the events on
the ground, the daemon is the studio deciding what's worth airing, and
ElevenLabs is the transmitter.

```
Claude Code / Codex does something
  ↓
a hook fires: python -m heard.hook <agent>        (short-lived, exits immediately)
  ↓ Unix socket
the daemon                                        (long-running, always on)
  ├─ tool calls  → canned templates               (cheap, no AI)
  └─ prose/finals → the "brain": one Haiku call    (decides what's worth saying)
  ↓
ElevenLabs → afplay → you hear it
```

The daemon is the only long-lived process. **No app, no menu bar, no window.**

---

## One-time setup

### 1. Environment

```bash
cd /Users/eberry/Code/apps/heard
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Python **3.13** is what's in use here. The project accepts 3.11–3.13.

### 2. Wire up your coding agents

```bash
.venv/bin/heard install claude-code
.venv/bin/heard install codex
```

**Only two names are valid: `claude-code` and `codex`.** The upstream
README mentions `codex-cli` and `codex-app` — those are **not** accepted
by this CLI and will exit with "Unknown agent".

This edits `~/.claude/settings.json` and `~/.codex/hooks.json`, **and
marks setup finished** so the daemon will narrate. That second part is
easy to miss — see Trap 1 below.

### 3. The two keys

| Setting | Why it's needed |
|---|---|
| `anthropic_api_key` | The narration brain. Without it you get canned templates only. |
| `elevenlabs_api_key` | The voice. Without it, everything runs but plays no sound. |

```bash
.venv/bin/heard config set anthropic_api_key sk-ant-YOUR-KEY
.venv/bin/heard config set elevenlabs_api_key YOUR-KEY
```

Both **take effect immediately** — `config set` pings the running daemon
to reload. No restart needed, including for the voice.

### 4. Autostart

```bash
.venv/bin/heard service install
```

Writes `~/Library/LaunchAgents/dev.heard.daemon.plist` and loads it. The
plist runs `.venv/bin/python3 -m heard.daemon` with `RunAtLoad` and
`KeepAlive` both on, so it starts at login and restarts if it dies.

---

## Two traps specific to this fork

### Trap 1 — the `onboarded` gate (fixed, but worth understanding)

**Symptom:** the daemon is alive, hooks are firing, and *nothing* happens.
The log fills with:

```
ev=event_drop kind=tool_pre tag=tool_bash_generic reason=not_onboarded
```

**Cause:** `heard/daemon.py` narrates nothing until the `onboarded`
config flag is true. That flag used to be set **only by the menu-bar
app's first-launch wizard** — and with no app, nothing ever set it, so a
source install was permanently mute. A **nightclub with no doorman**: the
door locked, and nobody coming to open it.

**This is fixed now.** `heard install <agent>` marks setup finished
(`onboarding.after_install` → `mark_onboarded`), because wiring up an
agent is the CLI's equivalent of closing the wizard.

There's also a **self-heal** for the case where the flag drifts back to
false on a machine that's plainly set up — a wiped config dir, the
corrupt-config auto-reset in `config._read_yaml`, an upgrade from an
older build. `onboarding.resolve_onboarded` treats **an installed agent
hook as proof setup happened**, reopens the gate, and writes the flag
back once (`ev=onboarded_healed`).

So if you ever hit `reason=not_onboarded`, **run `heard install
claude-code`** — don't set the flag by hand.

> Inside the `.app` bundle the self-heal deliberately stands down: there
> the wizard owns the flag, and it wires up the very hook we'd otherwise
> read as "done" — mid-flow, exactly when the gate should stay shut. It
> only applies to CLI installs like this one.

### Trap 2 — the `.env` file does nothing

**Nothing in the `heard` package reads `.env`, and that's deliberate.**
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `HEARD_BRAIN_MODEL` sitting in
the repo's `.env` are invisible to the daemon.

It isn't an oversight. The daemon is **one long-lived process shared by
every project**, normally auto-spawned by a hook, so it has no
per-project environment. One repo's `.env` would arm the keys narrating
every *other* repo, and which file won would depend on which project
fired first.

**Exporting in your shell doesn't reliably help either** — the daemon is
started by launchd at login or spawned by a hook subprocess, neither of
which inherits your interactive shell.

**Fix:** put everything in Heard's own config via `heard config set`.
Config is re-read on every event, so keys take effect with no restart.

> The brain *does* check `ANTHROPIC_API_KEY` as a fallback
> (`persona._anthropic_key`), which is why this is confusing — the
> mechanism exists, the daemon just never sees the value.
> `elevenlabs_api_key` isn't read from the environment at all.

---

## Day-to-day commands

All of these are `hidden=True` in the CLI, so they **won't show up in
`heard --help`.** They work fine.

```bash
# Is it alive? What's it doing?
.venv/bin/heard status

# Watch it work
tail -f ~/Library/Application\ Support/heard/daemon.log

# Speak a test line right now (skips the brain, goes straight to the voice)
.venv/bin/heard say "testing one two three"

# Stop it — launchd will restart it within seconds (KeepAlive is on)
.venv/bin/heard stop

# Run it in the foreground instead, with verbose per-event logging
.venv/bin/heard daemon --debug

# Read a setting (does not print secrets unless you name the key exactly)
.venv/bin/heard config get persona
.venv/bin/heard config path
```

To **truly stop** it rather than have launchd revive it:

```bash
.venv/bin/heard service uninstall
```

---

## How to tell it's actually working

Run `heard status`. A healthy daemon looks like this:

```
daemon:       alive (socket: /Users/eberry/Library/Application Support/heard/daemon.sock)
service:      installed
claude-code   installed
codex         installed

harness  (last 549 log lines):
  via:        harness=4 (33%)  fastpath=2 (17%)  v1-fallback=6 (50%)
  cache:      hit-rate 88%  (23 hits / 3 misses)
  synth:      p50=447ms  p95=380ms  (n=2)
```

Then grep the log for the three lines that prove each stage works:

```bash
grep -E "haiku_cache|event_speak|synth_ok" ~/Library/Application\ Support/heard/daemon.log | tail
```

**What good looks like:**

```
ev=haiku_cache path=harness:byok input=541 cache_read=11099 cache_write=0
ev=event_speak kind=intermediate persona=jarvis chars=78 via=harness
ev=synth_ok backend=ElevenLabsTTS ms=447 chars=92
```

- `path=harness:byok` — the **brain ran on your own Anthropic key**
- `via=harness` — the brain decided this, not a canned template
- `backend=ElevenLabsTTS` — **sound actually came out**
- `cache_read=11099` — prompt caching is working, which is what keeps
  the cost down (the persona and rules get resent every event; a cache
  hit means you don't pay for them again)

### Reading the counters correctly

`heard status` averages over a **trailing window of the log** (up to
5,000 lines — it prints how many it actually used). So it happily reports
a terrible punt rate long after you've fixed the cause, because the
window still contains the broken period. If the numbers look bad but
recent log lines look good, **trust the log lines.**

### `harness_skip` is not a bug

You'll see a lot of this:

```
ev=harness_think text="routine housekeeping on work already announced…"
ev=event_drop reason=harness_skip
```

That's the **brain choosing to stay quiet** — it judged repetitive tool
churn as not worth your attention. Like a good passenger who doesn't
announce every road sign. If it's too quiet for you, adjust `persona`
and the verbosity profile rather than assuming something broke.

---

## Troubleshooting

| What you see in the log | What it means | Fix |
|---|---|---|
| `reason=not_onboarded` | Setup was never marked finished | `heard install claude-code` (not the raw flag) |
| `ev=onboarded_healed` | Normal — a drifted flag self-repaired | Nothing to fix |
| `reason=no_voice_configured` | No TTS backend at all | Set `elevenlabs_api_key` |
| `via=floor` + `event_harness_punt` | Brain unreachable, using canned templates | Set `anthropic_api_key` in config (not `.env`) |
| `via=fastpath` | Normal — tool events never use the brain by design | Nothing to fix |
| `reason=harness_skip` | Brain chose silence | Nothing to fix |
| Nothing in the log at all | Hooks not installed | `heard install claude-code` |
| `daemon: stopped` | Daemon down | `heard service install`, or `heard daemon --debug` to watch it crash |

---

## Where things live

| Path | What |
|---|---|
| `~/Library/Application Support/heard/config.yaml` | **All settings and API keys** |
| `~/Library/Application Support/heard/daemon.log` | Structured event log (rotates at 10 MB) |
| `~/Library/Application Support/heard/daemon.sock` | Unix socket the hooks talk to |
| `~/Library/Application Support/heard/history.jsonl` | Everything it has ever spoken |
| `~/Library/LaunchAgents/dev.heard.daemon.plist` | Autostart definition |
| `~/.claude/settings.json` | Where the Claude Code hook is registered |
| `~/.codex/hooks.json` | Where the Codex hook is registered |

**Security note:** API keys are stored **in plain text** in
`config.yaml`. That's Heard's documented design, not something this fork
introduced — but it means a second copy of your keys exists on disk
alongside the repo's `.env`.

---

## Optional knobs

```bash
# Voice / tone, globally. Bundled: jarvis, aria, friday, atlas — plus the
# custom ones below. For a DIFFERENT voice per project, see the next section.
.venv/bin/heard config set persona jarvis

# Listening mode — copilot (default), companion, focus
.venv/bin/heard config set mode copilot

# How chatty — quiet, brief, normal, verbose
.venv/bin/heard config set verbosity normal

# Use a bigger model for narration (costs more per event than the default Haiku)
.venv/bin/heard config set brain_model claude-sonnet-5
.venv/bin/heard config set brain_model ""     # back to default

# Interactive walkthrough of voice / persona / verbosity
.venv/bin/heard tune
```

`brain_model` is an **experiment hook**. The default is
`claude-haiku-4-5`, which is what the narration prompts are tuned for and
what fits the latency budget.

---

## A different voice per project

**Drop a `.heard.yaml` in a repo root naming a persona, and that project
gets its own voice and personality.** One line:

```yaml
persona: radio
```

That's the whole setup. It takes effect on the next event — no restart.

### Why it works

On **every event**, the daemon reloads config against the event's working
directory ([`daemon.py:3078`](heard/daemon.py:3078)):

```python
cfg = config.load(cwd=cwd)        # layers .heard.yaml over global config
persona = self._persona_for(cfg)  # persona comes from that merged config
```

and the voice is picked at [`daemon.py:1669`](heard/daemon.py:1669):

```python
return persona.voice or cfg["voice"]
```

So the **persona carries the voice**, and the project file picks the
persona. Think of it as a **name badge at the door** — the daemon checks
which repo an event came from and puts on the matching costume.

### The persona library

Custom personas live in
`~/Library/Application Support/heard/personas/<name>.md` and **override
bundled ones with the same name**.

| `persona:` | ElevenLabs voice | Character |
|---|---|---|
| `radio` | 1920s Radio Storyteller | Newsreel announcer, live bulletins |
| `brian` | Brian — deep, resonant | Documentary narrator, slow and awed |
| `spuds` | Spuds Oxley | Old workshop hand, warm, unhurried |
| `warrior` | Harry — fierce warrior | Campaign framing, every bug an enemy |
| `callum` | Callum — husky trickster | Sly co-conspirator, enjoys a failure |
| `jess` | Jessica — playful, bright | Fast, upbeat teammate |
| `roger` | Roger — laid-back | Unbothered, for low-stakes side projects |
| `river` | River — neutral | Flat and precise, no character at all |

Plus the four bundled ones: `jarvis`, `aria`, `friday`, `atlas`.

### Auditioning a voice

```bash
.venv/bin/heard config set persona radio
.venv/bin/heard say "Testing the newsreel voice, folks."
.venv/bin/heard config set persona jarvis
```

### Adding your own

List your ElevenLabs library to get voice IDs (this makes a network call):

```bash
.venv/bin/heard voices --all
```

Then copy any file in the personas folder and change the `voice:` ID and
the prompt body. Only these frontmatter fields are actually read into the
persona: **`name`, `voice`, `kokoro_voice`, `address`, `templates`**, plus
the Markdown body as the system prompt.

Keep the body to **character only** — tone, address rules, stylistic
anchors. Brevity, "never read code aloud", and tense are already handled
by `_SHARED_NARRATION_RULES` in `heard/persona.py`, which gets prepended
to every persona prompt.

### Four traps

**1. `speed:` and `verbosity:` in a persona file do nothing here.**
`_persona_from_md` doesn't read them — only `heard tune` and the menu bar
do, via `load_meta`. To vary them per project, put them in the
`.heard.yaml` instead:

```yaml
persona: warrior
speed: 1.1
verbosity: brief
```

**2. A typo'd persona name fails completely silently.** An unknown name
falls back to `raw` — **no voice and no personality prompt** — so you get
the global default voice reading flat text, with no error and no log
line. If a project sounds wrong, check the spelling first.

**3. `voice:` in `.heard.yaml` is ignored** whenever the active persona
declares its own voice, because `persona.voice` wins. All bundled
personas declare one. Set the persona, not the voice.

**4. `agent_voices` does nothing when you're on one project.** The
global config has a `repo_name → voice_id` map that looks perfect for
this, but every code path that applies it short-circuits unless **2+
agents are active at once**. It's for telling parallel agents apart, not
for per-project voices.

### Voices your subscription lists but cannot use

**"Famous" voices are blocked from the API**, even on a paid plan:

```
401 voice_access_denied
"Famous voices can only be used within the Reader App."
```

`heard voices --all` will happily list them. They only work inside
ElevenLabs' own Reader app. **Test-synthesize any new voice before
relying on it** — otherwise that project just goes quiet.

---

## What to ignore in the upstream docs

These are all app-only and **do not apply here**:

- **"Download `Heard.zip`, drag into `/Applications`"** — no app is used.
- **The hot-patch workflow** in `AGENTS.md` (`rsync` into
  `/Applications/Heard.app/…`, `killall Heard`, `open`) — there's no
  bundle to sync into. Just restart the daemon.
- **The py2app build** (`packaging/setup.py`, `build-app.sh`,
  `app_entry.py`) — never run here.
- **Anything about the menu bar** — Settings panel, onboarding wizard,
  Active-agents menu, `heard ui`. All of it needs AppKit and a running
  app. Use `heard config set` and `heard status` instead.
- **Sign-in / managed plans** — the managed tiers assume the app's
  sign-in flow. This setup is the **self-host path**: your own keys, no
  account.

Still fully relevant in `AGENTS.md`: the **process model**, the **module
map**, and the **coding conventions**.

`AGENTS.md` and `README.md` now carry their own **CLI-only** sections, so
they're largely accurate for this fork. `CONTRIBUTING.md` is the one
still written entirely around the app.

---

## Divergence from upstream

This fork carries a few changes upstream doesn't have. Worth knowing when
you pull from `heardlabs/heard`:

- **`heard install <agent>` marks onboarding complete**, plus the
  hook-based self-heal in `onboarding.resolve_onboarded`. Upstream still
  relies solely on the GUI wizard.
- **`.env` is gitignored** and `.env.example` no longer claims that
  copying it to `.env` configures anything — it doesn't.
- **This file**, plus the fork-only rule in `CLAUDE.md` and the guard in
  `.claude/hooks/fork-guard.sh`.
