# Architecture and adapter contract

The workbench keeps Sebastian's implementation outside this repository. `--upstream` points to a local checkout. Its `run_pipeline` executes in a child process using the configured Python environment. Viewing and importing existing exports need no model dependencies.

`adapter.normalize` maps a SAST result into items with attribute-name-derived stable IDs, candidate IDs derived from validated mapping strings, the original machine mapping, matrix and complete state/logs. `runs.raw` stores the imported output in full with a SHA-256 hash. Review actions never update it.

`Store` uses SQLite transactions. `items.version` starts at 1 and increments on human decisions. `events` append posts, replies and decisions against an item version. `parent` identifies replies; candidate IDs link posts to validated candidates. Stale decisions return HTTP 409. Agent posts are labeled as agent output and include model/prompt metadata; they cannot change human decisions or machine output.

A later RQ1 adapter can share these records and interface patterns, but must define RQ1-specific items, evidence references, revision operations and decision validation. The current accepted-state validator requires one SAST mapping candidate, which would be incorrect for requirement consensus.

The original council turns are displayed from the SAST export. The optional workbench agent review is a new two-role, bounded call sequence; it is not the paper's full interactive blackboard. Its effects must be evaluated separately.

The server binds `127.0.0.1`. POSTs require a per-server token and Host/Origin checks. Names are self-declared. Saved records and imported files stay local except when a configured model call sends selected context to the original project's provider.
