# Ekalavya configuration

Configuration is user-owned availability policy. It determines which
providers, catalogue routes, and named local routes are eligible; it does not
change profile defaults or perform hidden failover.

Inspect it with:

```bash
eka config
eka config list --json
```

Explicit changes use:

```bash
eka config enable <route>
eka config disable <route> --reason "maintenance"
eka config enable-provider <provider>
eka config disable-provider <provider> --reason "quota policy"
```

`eka config migrate` is an explicit, additive migration operation. It keeps
the source intact and is not part of ordinary discovery or status. Normal
runtime reads the active Ekalavya configuration only.

The file contains enabled flags and human-readable reasons, never credentials
or tokens. Experimental routes default to disabled until the user opts in.
Agents may inspect and respect this state, but must not mutate it merely
because a quota or resource looks low.

Configuration writes are atomic. Invalid names, sections, or values fail
without inference. `eka doctor` checks readability and ledger integrity.
