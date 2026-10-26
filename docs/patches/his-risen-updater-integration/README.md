# Updater integration patch set

These four patch files preserve the code-level diff for review. They are patches against the controller package extracted from the existing `apps/his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip`; their paths are relative to the **extracted controller root**, not the repository root.

Apply order:

1. `01-director-console.patch`
2. `02-update-checker.patch`
3. `03-console-tests.patch`
4. `04-updater-tests.patch`

From a clean extracted controller folder, run `git apply --check` on each patch before applying them. These patch files are review aids only; committing them does not update the application ZIP or deploy anything.

The tested candidate archive is named `his_risen_controller_ltx25_updater_ui_integrated_2026-10-26.zip` and has SHA-256 `77c74f84e1e94e356ac818d6aff92117db10470908963186138f98ca8bf65229`. The full test and deployment-gate notes are in `docs/UPDATER_HARDENING_AUDIT_2026-10-25.md`.
