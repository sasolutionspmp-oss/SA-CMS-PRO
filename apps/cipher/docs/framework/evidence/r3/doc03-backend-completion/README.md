# DOC-03 backend evidence

`MANIFEST.json` identifies direct feature paths versus shared integration fragments and binds the isolated 918-file source tree. `QUALIFICATION.json` and `FAILURES.json` describe the 109 distinct host cases and retained attempts. The full combined run passed 65 DOC-03 cases; its one stale SQL fixture was corrected and the affected case passed separately. Three additional host regressions cover the local-native findings. Forty source-compatibility cases passed with the declared fixture composition. Counts overlap earlier focused logs and must not be added to them.

`qualified-composed-source-v2.tar.gz` is an exact source snapshot, not a deployable release or a replacement for the local Task overlay. Verify its SHA256 against `QUALIFIED_ARCHIVE_MANIFEST.json` and extract only into an empty inspection directory. The manifest pins every member. Dependencies, secrets, runtime configuration, database volumes, model weights and caches are excluded.

`integration-fragments/` holds shared-source diffs and documentary core-definition additions. Generated artifacts are recorded by hash for source binding; the local coordinator regenerates them after merging Task changes. `lifecycle-freeze/` preserves the focused child boundary and qualification. `logs/` retains all current attempt logs, including genuine failing-first regressions and test-double setup failures.

The original WIP and Project checkpoints remain available at the pinned refs in the [handoff](../../../DOC03_BACKEND_FINISH_HANDOFF.md). Current native workflows are declarations only. No browser/native/concurrency or complete C20 acceptance is claimed.
