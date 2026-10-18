# Capability-Aware Recovery Router

This package is a reusable, domain-independent pattern for routing a filtered set of safe actions through a Strands Decider service. It validates a complete capability-filter partition, enforces trusted model capacity before HTTP, preserves the model choice separately from a conservative effective choice, and invokes exactly one callback from an immutable label registry.

## Safety and protocol properties

- Only literal `http://127.0.0.1:<port>` and `http://[::1]:<port>` origins are accepted.
- Response bodies are bounded to 64 KiB and decoded as strict UTF-8, finite, duplicate-free JSON.
- Choice labels, probability keys, probability sum, maximum choice, confidence formula, usage, and trusted model identity are validated before dispatch.
- Zero or one choice returns `INSUFFICIENT_CHOICE_CARDINALITY`; choices above trusted capacity return `UNSUPPORTED_CHOICE_CARDINALITY`. Neither path makes HTTP or invokes a callback.
- A low-confidence model choice remains in evidence while a configured eligible fallback becomes the effective choice.

## Document-processing example

The example has no telecom dependency. It checks `/health`, uses the same canonical real-client path as the router, filters text extraction by local parser availability, and records the selected callback.

```sh
STRANDS_DECIDER_URL=http://127.0.0.1:8000 \
  uv run python -m patterns.capability_aware_router.examples.document_processing

uv run python -m patterns.capability_aware_router.examples.document_processing --help
```

The Decider service must already be running locally; this package does not download a model or start a service.
