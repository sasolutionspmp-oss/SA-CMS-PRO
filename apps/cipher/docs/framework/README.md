# Cipher framework and implementation

**Implementation authorized:** The owner instructed “Execute this plan as written and do not stray” on October 15, 2026. Implementation is now active under this framework. Earlier pending-approval/planning-only markers describe the completed draft stage and no longer block coding. Astra ultra owns orchestration/reviews/escalations; all implementation subagents use GPT-6.1 Sol.

**Implementation worktree:** `/workspace/cipher-framework-draft`

**Branch:** `cipher/framework-final-draft`

**Product:** Cipher — The AEC/CMS Pro

**Implementation approval:** granted; source implementation, runtime verification and review are active.

Start with [current implementation status](IMPLEMENTATION_STATUS.md) for actual results, live-browser captures and the next work. The documents below retain the approved full scope.

The [live build walkthrough](LIVE_BUILD_WALKTHROUGH.md) links the actual container screenshots in workflow order.

The source worktree remains separate and retains its existing uncommitted development. This branch starts from `a84cde6ac1b633450d7a122549b6bf9589ec8bc3`; seven current planning documents were copied explicitly as historical planning context. The latest owner correction excludes all prior Cipher/Odoo work as design inputs. The standalone framework and its companion contracts govern this new product; inherited repository files are outside the target build/import boundary.

## Read in this order

1. [Backend framework](BACKEND_FRAMEWORK.md): comprehensive architecture, data/domain contracts, transactional behavior, accounting ownership, API contracts, embedded Ricky, deployment and autonomy rules.
2. [Execution backlog](EXECUTION_BACKLOG.md): 66 dependency-ordered work packages, releases and required evidence.
3. [Completion matrix](COMPLETION_MATRIX.md): 26 end-to-end scenarios defining completion.
4. [Decisions and dependencies](DECISIONS_AND_DEPENDENCIES.md): settled defaults, genuine external dependencies and the implementation authorization boundary.
5. [Platform](../../platform/README.md) and [product](../../product/README.md): application code, local deployment, client and module ownership.

The backend has 16 planned module boundaries, implemented in dependency order. Unimplemented module README specifications are not executable capabilities. `backlog.json` tracks current work and qualification; it is not application configuration. The development runtime and source-bound evidence now live alongside this framework. Historical `SOURCE_MANIFEST.json`, `VALIDATION_REPORT.json` and the original draft ZIP describe the planning snapshot, not the current executable release.

## Settled implementation authorization

The selected architecture, product boundaries, default technical decisions, phased scope and autonomous execution process are approved. Engineering implements and verifies ready tasks without requesting routine design choices. Actual secrets, optional business-data onboarding, licensed inputs and real-world consequential actions remain specific external dependencies; they do not stop independent work.

The full plan is intended to support sustained, resumable implementation. It cannot guarantee uninterrupted multi-day execution or predict every external dependency. Durable handoffs and a dependency-aware backlog prevent avoidable restarts and repeated owner supervision.

**Clean design rule:** Odoo is interim operations only. New architecture, schemas, workflows, UI and acceptance fixtures derive from current requirements and selected open-source platforms. No recovery of prior work blocks design or implementation. Any eventual business-data transfer maps into the finished target model.
