# Tests belong to the role that owns the code under test

Per the ownership map in [`/CLAUDE.md`](../CLAUDE.md):

| suites | role |
|---|---|
| `conftest.py`, `agent_harness.py`, new regression tests anywhere | **QA** |
| `js/**`, `test_frontend_*.py`, `test_models_drawer_render.py`, `test_connector_catalog_ui.py` | **Frontend** |
| `test_api_surface.py`, `test_local_api_origin_guard.py`, `test_threadpool_isolation.py`, `test_failures_are_recorded.py` | **API** |
| `test_agent_*.py`, approvals / routines suites | **Agents** |
| `test_brain_v15_*.py`, `test_canonical_brain.py`, `test_core.py`, `test_sqlite_row_membership.py` | **Brain** |
| `test_model_*.py`, `test_provider_*.py`, `test_auth_flow_unification.py`, `test_plan_*.py`, `test_*subscription*.py`, `test_cli_manager.py`, `test_native_accounts.py`, `test_credential_independence.py`, `test_detection_is_not_consent.py`, `test_vendor_identity.py` | **Models** |
| `connectors/**` | **Connectors** |
| `test_signin_hud*.py`, `test_desktop_port.py` | **Desktop** |

Four standing rules, all bought the hard way:

- **A test must never start a real sign-in.** `conftest.py` swaps the argv of any
  `login` spawn — past hygiene failures left a `claude auth login` alive on every
  pytest run, wrote to the real Keychain, and bound the fixed OAuth port 1455.
- **Never delete, skip or weaken a test you do not own**, and never re-baseline
  `api_surface.json` to get green. That is a handoff, with the reasoning, in
  `.claude/fleet/HANDOFF.md`.
- **A bug fix ships with a regression test.** Always.
- **Execute frontend render paths and click handlers** — `tests/js/` harnesses
  exist because `node --check` and source-order assertions pass while a TDZ error
  or a detached container has broken the screen. When you write a harness, verify
  it fails with the bug reintroduced before trusting it.

Adding a test file to another role's area is fine. Editing their existing tests is
not.
