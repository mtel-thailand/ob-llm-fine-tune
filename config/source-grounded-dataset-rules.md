# Source-grounded dataset rules

1. Generate every dataset fact only from the current selected source code, code digest, graph context, existing test, configuration, or real supplied runtime log.
2. Never invent a runtime log, stack trace, endpoint, Kafka topic, database table, service relationship, error code, request payload, incident, or production fix.
3. When a runtime log or error is absent from current evidence, state that it is unavailable and require real evidence before diagnosing a production incident.
4. Cite the repository, path, and line range that support every behavioral claim.
5. Use graph context only to locate related source. Do not present a graph edge as proof of runtime behavior.
6. Keep generated records in `needs_human_review` until an authorized reviewer confirms them for training.
