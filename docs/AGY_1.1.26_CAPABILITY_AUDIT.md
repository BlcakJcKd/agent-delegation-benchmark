# AGY 1.1.26 capability audit

This is a zero-inference harness audit performed on 2026-09-04.  The locally
installed client reports version `1.1.26`.

The 1.1.26 help exposes `--sandbox`, `--add-dir`, and ordinary model/effort
selection.  The 1.1.26 changelog describes UI, session persistence, and
subagent fixes, but exposes no supported mechanism for attaching an
independently contained candidate-tool subprocess, container, or network
namespace while leaving AGY provider transport outside that containment.

Accordingly the registry records:

- ordinary delegation: supported;
- public characterization: supported;
- hidden benchmark: unsupported;
- exact model and reasoning selection: supported;
- writable workspace: supported;
- filesystem containment: unsupported;
- candidate-tool network containment: unsupported;
- tool trace: unavailable;
- provider transport: supported;
- token usage: supported as harness-reported usage only;
- billing/cost usage: unavailable.

No conditional containment probe was run because the required new mechanism
was not exposed.  Image-input and browser/rendered-page capabilities were not
established and are not inferred from the model catalogue.
