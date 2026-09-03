# Optional metered providers

Optional pay-as-you-go providers are exposed through Ekalavya profiles and
remain disabled by default until the user explicitly enables them.

Inspect state without inference:

```bash
eka status --primary <identity>
eka config --json
eka models --json
```

Enable a provider or route only after checking the user's billing and quota
policy:

```bash
eka config enable-provider <provider>
eka config enable <route>
```

Use `eka run <profile>` with a bounded workspace, timeout, and explicit
primary identity. The adapter retains response evidence and reports failures
without silent provider substitution. Provider-reported cost is recorded only
when actually exposed; otherwise cost remains null. Hypothetical API-equivalent
cost is labelled separately.

Availability is user-owned state. Agents must not enable, disable, or reroute
metered capacity merely because another route is busy or low on quota.
