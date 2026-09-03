# Ekalavya control plane

Ekalavya is the operational layer around the existing benchmark. A run is
represented as `intent -> profile -> explicit resolution -> adapter -> private
evidence`; `status`, `history`, and `spend` read recorded state and do not
re-resolve or dispatch work.

Profiles are stable capability names. A configured default is selected only
because the caller explicitly invoked that profile. No automatic provider
failover exists. The resolver retains both requested intent and resolved
candidate, rejects unsupported reasoning locally, and returns
`same-provider-native-required` for Codex/Codex, Claude/Claude, or
Gemini/Gemini external calls. Same-provider native work belongs to that
provider's native agent facility.

The private catalogue distinguishes provider, family/lineage, exact provider
model ID, variant, capabilities, harness, transport, and local serving
metadata. A family normally has `current`, `previous`, and `candidate` live
states. Discovery can add candidates but cannot promote them. Retirement
removes normal selection while preserving ledger evidence.

The private SQLite ledger is versioned and normalized around model identities,
availability, profiles, harnesses, engines, hardware, benchmark identity,
runs, task attempts, requests, tool events, prices, costs, lifecycle events,
resolution decisions, and imported evidence hashes. Raw responses remain in
their existing private locations and are referenced by path/hash rather than
copied into the database. Import is additive and idempotent.

Cost fields are intentionally separate: provider-reported actual cost,
calculated cost using an immutable price snapshot, and API-equivalent cost.
Subscription and local routes have null actual cash cost unless the provider
reports one; local resource measurements remain separate from spend.

`ekalavya config migrate` copies legacy configuration without deleting it,
preserving file permissions and reporting conflicts. `models refresh` is an
explicit file-driven discovery path in V1; it marks entries as candidates and
does not contact providers or change defaults. A future provider adapter may
populate the same catalogue contract.

The old `ask-*`, `delegate-status`, `delegate-config`, and `ask-vllm` commands
remain compatibility commands. They retain their existing scope, closed
stdin, recursion, timeout, process cleanup, and response-retention behavior.
New agent instructions and examples use `eka` exclusively; compatibility
entry points are retained for existing scripts during the deprecation period.
