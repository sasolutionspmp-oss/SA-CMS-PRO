# Faster delivery to human trials

Execution update: October 17, 2026. This changes how we deliver the approved framework, not its architecture or scope. SAP UI5/Horizon, ERPNext/Frappe, Cipher AEC, QuickBooks accounting authority and the Ricky adapter remain the design. Odoo and prior Cipher implementations remain excluded.

## Decision

Use a hybrid setup: a persistent local Docker sandbox for human trials and integration, with cloud agents and hosted CI for development and independent checks. Git is the handoff between machines. Do not copy the cloud container as the deployment artifact or share a live database between development environments.

The immediate milestone is a usable trial release of existing workflows. It does not wait for all 66 packages or enterprise acceptance. Continue the original dependency order for implementation; bring human feedback forward.

## Observed limits and available resources

- Current cloud container: 16 GiB memory limit, about 14.2 GiB used, four-CPU quota, 19 MB available on the root filesystem; /tmp has about 448 MB available. Measured October 17, 2026.
- /dev/shm has space but is memory-backed and temporary. More copies there consume the same memory budget; it is not a durable capacity upgrade.
- GitHub repository and hosted native CI are available. Latest published engineering source f79df23af5bdb1c8cccf538241452bef2c459672 passed all 26 hosted stages.
- Project document-control UI is built and typechecked. Its 30 distinct focused checks now pass across retained runs and targeted continuations; this is not a fresh 30-case run or native UI qualification.
- A local Docker development stack already exists with MariaDB, Redis and the Frappe/Cipher runtime. It requires a prepared image and installation; it is not yet a portable one-command trial installer.
- No local-machine execution connection or VPN capability is configured in this session. Local CPU/RAM/OS and Ricky's resource use are unknown. A local Codex session can work from the same Git repository; that does not transfer this running cloud conversation or grant it local access automatically.

The deployment audit identified specific portability work: the default runtime image tag exists only in the current environment; app/UI files are bind-mounted; startup installs dependencies; site/ports and a Unix Docker socket are fixed; CA mounts and UID assumptions need platform handling. The cloud image-flattening helper is amd64-specific and should not be required for ordinary local Docker. Existing basic seeds need explicit engineering/Company permissions and usable sample documents, rates and units. Reuse the existing bootstrap, installation and backup/restore routines rather than writing competing systems.

## Compute arrangement

Recommended starting host, pending actual machine details: 64 GB RAM, at least 8 CPU cores and 150 GB free SSD. A 32 GB host may be sufficient for a smaller trial; measure before adding parallel workloads. These are planning targets, not benchmarked requirements.

Initially allocate Docker 16–24 GB RAM and 6–8 CPUs on the 64 GB host, leaving room for the OS and tools. Use Linux containers; on Windows use WSL2 and keep the checkout inside its Linux filesystem. Verify image architecture on ARM machines. Account separately for Ricky's model RAM/VRAM; the ERP itself does not need a GPU.

| Resource | Responsibility |
| --- | --- |
| Local stable sandbox | Human trial sessions, persistent sample projects, feedback and screenshots |
| Local integration environment | Install candidate images, migration and browser checks; separate volumes from the stable sandbox |
| Cloud workspace | Bounded implementation, source review, coordination; avoid heavyweight parallel builds |
| Hosted CI | Fresh installation, native integration and release regression checks |
| Git | Reviewed source commits, task ownership and reproducible version handoff |

A larger dedicated Linux VM is the fallback if local hardware is unavailable. Provisioning or paid capacity is not assumed. Do not add Kubernetes or multiple servers to solve this stage's needs.

## Delivery sequence

1. **Land the completed work.** Publish the current Project document-control candidate and retained test outcomes; preserve the interrupted successor work separately. Stop repeating unchanged local suites. Obtain the hosted native result for the published candidate.
2. **Make the sandbox portable.** Add a separate trial Compose project, reproducible pinned image build, environment template, fresh-site installer, sample-data bootstrap and start/status/stop/backup/restore commands. Parameterize site and ports. Remove reliance on this cloud machine's local image tags, proxy setup and CA paths. Use private configuration files for credentials. Keep existing MAIN and its volumes untouched.
3. **Install a candidate locally.** Use a reviewed Git SHA, image digest and fresh named volumes. Give the trial persistent accounts with separate PM, estimator and reviewer roles. Seed sample business records through supported application APIs. Sample data must run on real Frappe persistence, without browser request mocks. Record exactly which candidate is installed.
4. **Release the first human trial.** Verify login, a project/task/document journey, proposal/estimate drafting, engineering review and document issue/transmittal wherever the candidate supports them. Limit the first session to three short tasks. Unsupported actions stay unavailable and clearly labeled. Verify saved changes after reload and restart, role separation, and one meaningful retry case. Capture actual screens from that runtime.
5. **Fix trial blockers first.** Rank feedback: cannot finish task, misleading/wrong result, confusing workflow, then visual polish. Resolve the top blockers and give the tester an updated sandbox. Keep the stable trial usable while the integration environment changes.
6. **Continue the original backlog.** Complete remaining DOC-03 Company library/clause/lifecycle work and other ready packages against the same contracts. Advance procurement/finance only when their dependencies are genuinely ready. The previously blocked award action remains blocked; a hardware move must not be used to rerun it elsewhere.
7. **Expand trials by real workflow.** Add connected purchasing, AP/AR and QuickBooks sandbox integration as their dependencies qualify. Add real Ricky inference when its connection contract is available. Each slice ends with a person completing a business task in the unified application.

## Parallel work without duplicate effort

Start with three implementation lanes plus the coordinator, not the maximum possible number of agents. Use GPT-6.1 Sol Ultra as requested. Add workers only when a ready task has a clean ownership boundary and measured compute headroom.

- Backend lane: remaining original DOC-03 services, data contracts and meaningful affected tests.
- Product lane: SAP UI5 workflows and plain-language copy using agreed generated types.
- Sandbox lane: portable image/Compose, sample bootstrap and runtime trial verification.
- Coordinator: owns integration, shared schemas, cross-lane API decisions and the release candidate.

Each lane gets a branch or sparse worktree, a written outcome and named owned paths. Shared schema changes have one owner; consumers use a fixed contract revision. No two machines write the same worktree. Only the coordinator advances the integration branch. One integration database writer at a time; agent development uses separate fixtures/sites when needed.

Do not create one full repository copy, dependency install or runtime per agent. This repository has historically committed node_modules outside the new build; use sparse checkouts and caches. Cloud and local workers exchange commits and compact handoffs, not long copied chat histories.

More RAM speeds compilation, browsers and databases. It does not increase model quotas or make model inference local. Additional agents consume additional credits; count completed, accepted workflow slices rather than active agents.

## Checks and release cadence

During implementation run affected domain/adapter tests and one relevant UI journey. On an integrated candidate run typecheck/build once and the required hosted suite. Rerun unchanged work only for a changed dependency, real failure or unresolved concern. Preserve required repository commit checks and reuse permitted unchanged proofs.

Keep authorization, money calculations, data isolation, persistence and duplicate-effect recovery in the minimum trial gate. Human trials find workflow and language problems; they do not replace these controls. Defer comprehensive visual polish and enterprise load qualification until representative workflows are used.

The trial gate is: actual login, real database and document bytes, core task completed, state survives restart, scoped access enforced, backup/restore path exercised, known gaps listed and actual screenshots attached. First trial is a subset of the completion matrix, not a claim that the ERP is complete.

Target a reviewable increment every working day once setup is stable. This is a delivery cadence, not a promise of unattended execution or a completion date. Measure time to first trial, user task success, blocking defects, candidate turnaround and rework. Keep one concise status note: available now / next / blocked.

## Product language

Use the words a PM, estimator or accountant would use. Buttons name the action; status messages state the outcome. Put hashes, immutable identifiers and technical audit details behind Details. Keep a warning visible only when it affects the user's decision. Preserve precise commercial meaning: recording an acknowledgment must not claim that delivery, signing or legal execution occurred.

| Current UI wording | Proposed wording |
| --- | --- |
| Saved with the exact original revisions and operation receipt. | Saved. |
| Loading authorized document records… | Loading documents… |
| Author library successor | Create revision |
| Prepare Project adoption | Use in project |
| Related retained records | History |
| Earlier retained source | Previous revision |
| Refresh retained record | Refresh |
| Report receipt evidence | Record acknowledgment |

These are examples for the product lane, not claims that source copy has already changed. A reviewer must check whether a shorter label changes the business meaning. Avoid generic legal or implementation paragraphs on routine screens. Error messages explain what happened and the next useful action.

## Local handoff and boundaries

Git commits carry application source and reproducible deployment instructions. They do not carry secrets, mounted database directories, browser sessions or cloud-only temporary evidence. Retain the durable source/evidence checkpoint before ending the cloud environment. Backup/restore application data separately if a later migration actually needs it; the initial local trial starts fresh.

Before local execution, collect OS, CPU, RAM, free SSD, Docker availability, local Codex availability and Ricky resource needs. No local credentials are requested in chat. Start with a local Codex session and repository checkout; consider authenticated remote access only if ongoing remote operation is useful. A self-hosted CI runner is optional later, not a prerequisite for the first trial.

## References reviewed

- [Approved completion matrix](COMPLETION_MATRIX.md) and [execution backlog](EXECUTION_BACKLOG.md).
- [Existing Cipher deployment](../../platform/deployment/README.md) and [Compose stack](../../platform/deployment/compose.dev.yml).
- [Official Frappe Docker](https://github.com/frappe/frappe_docker): supports custom-app images and Compose; its disposable demo is not the Cipher application.
- [Official Codex CLI](https://github.com/openai/codex): local coding execution.
- [Docker Desktop resource settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/): resource configuration and platform differences.

No new local sandbox has been deployed by this planning update. Local capacity, installation and trial results remain to be verified.
