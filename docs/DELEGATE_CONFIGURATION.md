# Ekalavya configuration

Configuration is user-owned availability policy. It determines which
providers, catalogue routes, and named local routes are eligible; it does not
change profile defaults or perform hidden failover.

For human interactive configuration, run this from a TTY:

```bash
eka config
```

It shows separate checkbox sections for providers, models, and named vLLM
routes. Changes are staged until Save; Cancel makes no changes. Provider
toggles do not rewrite model preferences: a model can remain configured
enabled while being effectively unavailable because its provider is disabled.

For inspection without a terminal UI, use the deterministic JSON form:

```bash
eka config --json
eka config list --json
```

Explicit changes use:

```bash
eka config enable <route>
eka config disable <route> --reason "maintenance"
eka config enable-model <model>
eka config disable-model <model> --reason "maintenance"
eka config enable-provider <provider>
eka config disable-provider <provider> --reason "quota policy"
```

Model and provider names are checked against Ekalavya's known catalogue. Named
vLLM routes are checked against configured local route names; typos fail
without creating new keys. When stdout is not a TTY, `eka config` emits the
same deterministic inspection payload rather than attempting an interactive
screen.

`eka config migrate` is an explicit, additive migration operation. It keeps
the source intact and is not part of ordinary discovery or status. Normal
runtime reads the active Ekalavya configuration only.

The file contains enabled flags and human-readable reasons, never credentials
or tokens. Experimental routes default to disabled until the user opts in.
Agents may inspect and respect this state, but must not mutate it merely
because a quota or resource looks low.

Configuration writes are atomic. Invalid names, sections, or values fail
without inference. `eka doctor` checks readability and ledger integrity.
