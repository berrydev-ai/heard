# Heard

The contributor and coding-agent guide lives in [`AGENTS.md`](./AGENTS.md) —
process model, module map, coding conventions, the hot-patch workflow, and
how to run tests. Start there.

## This is a fork — never push or PR upstream

**All commits, branches, and pull requests go to `berrydev-ai/heard` only.**
This checkout is a fork of `heardlabs/heard`, and nothing here is ever
contributed back upstream.

- **Push only to `origin`** (`git@github.com:berrydev-ai/heard`). It is the
  only remote, and it must stay that way — do not add an `upstream` remote.
- **PRs must target `berrydev-ai/heard`.** `gh` is pinned to it via
  `remote.origin.gh-resolved = base`. Never pass `--repo heardlabs/heard`
  or a `--base` that resolves upstream. Beware: `gh pr create` on a fork
  defaults to the PARENT repo when that pin is missing.
- **Never open issues, PRs, or comments on `heardlabs/heard`.**
- If a task seems to require upstream access, **stop and ask** — do not
  work around the restriction.

This fork is also **CLI-only** — no `Heard.app` is built or installed. See
[`RUNNING_LOCALLY.md`](./RUNNING_LOCALLY.md) for the setup that applies
here, and treat the app-centric parts of `AGENTS.md` / `README.md` as not
applicable.
