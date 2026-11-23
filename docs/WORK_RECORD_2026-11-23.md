# Work record — 2026-11-23

Scope: the workflow section of the console, plus the run journal field needed
to make a failed run resumable from the UI. The deep-space visual system and the
twelve-section layout are unchanged.

## Workflow definition editing

- Every definition card now has `编辑` and `带入执行` actions.
- `编辑` loads the stored definition into the existing registration form, locks
  the workflow id, switches the submit button to `更新定义`, shows the edit note,
  and exposes a `取消编辑` button.
- Saving in edit mode posts to `POST /api/v1/workflows/<id>`; creating still
  posts to `POST /api/v1/workflows`. The console reports a server refusal
  verbatim and never changes the definition locally before the server accepts it.
- The node textarea grows from 7 rows up to 16 rows when an existing definition
  is loaded, so a multi-node definition is visible without silently hiding the
  second node behind a scrollbar.
- Four node templates insert a real JSON node: `rule_check`,
  `change_detection`, `artifact_register` and `model_chat`. The insertion
  generates a non-duplicate node id and name; it does not overwrite the existing
  node list and does not submit anything.
- `带入执行` selects the same definition in the execute form and scrolls there.
- While editing, the source definition card carries an accent edge and an
  `编辑中…` badge, so the list and the form do not disagree about which record is
  open. Cancelling or saving removes both marks.

## Resume a failed run

- The run journal now records `workflow_id` next to `task_id`, `project_id` and
  `actor`. Existing journal rows without the field still load and still render;
  new runs and resumed runs carry it.
- Failed or errored run cards expose `恢复运行`. The action fills the existing
  execute form rather than creating a second form: it selects the previous run,
  selects the recorded workflow when that definition is still present, and
  fills an empty task id from the run.
- The form's action switches from `执行流程` to `恢复运行` while a previous run
  is selected. On submit it posts to
  `POST /api/v1/workflow-runs/<run_id>/resume` with the selected
  `workflow_id`, task id and context.
- Context is deliberately not stored in the journal. The operator must supply
  the paths again; the console does not invent them from a prior run.
- A successful resume clears the previous-run selection, renders the new run
  output and reloads the journal. A refusal leaves the selection and form intact.

## Run history filter

- The run history has a local search field that matches run id, status, task id,
  workflow id, `resumed_from`, node id, node name and node detail. It is a read
  filter over the already-fetched journal; it never asks the server to hide a
  row and never invents a result.
- While filtering, the count pill shows `shown / total`; with no query it shows
  the total. `Esc` clears the field and restores the full list.
- The failed-run selector used for resume is built from the unfiltered journal,
  so narrowing the visible history cannot silently remove a resumable run from
  the form. A no-match state says `没有匹配的运行`, not `还没有运行记录`.


## Verification

- `node --check geoops/web/ui.js`: pass.
- Targeted tests: `geoops.tests.test_ui`, `test_workflow_definition`,
  `test_journal` — `Ran 43 tests`, `OK`.
- Full suite: `Ran 390 tests in 33.457s`, `OK`.
- Smoke: `SMOKE PASS: 73 assertions`.
- Browser fixture with three definitions and one real failed run:
  - edit opened the stored definition with the id locked and one node; the
    active card carried `is-editing` plus the `编辑中…` badge, and both cleared
    after cancel;
  - a node template added a second node (`C1 · change_detection`);
  - saving updated the definition to `v2`, two nodes, and the API returned
    `200` with the new name and description;
  - cancel restored create mode without changing the server record;
  - the failed run (`G1 · gis_tool_call`) resumed as `PASS` with
    `resumed_from` pointing at the failed run and `workflow_id=WF-UI-RESUME`
    in the journal;
  - the run filter matched one `FAIL` run and showed `1 / 1 次`; a
    non-matching query produced `没有匹配的运行`; clearing restored the list,
    and the resume selector kept both options throughout;
  - 1280 px and 390 px both reported `overflowX=0`; template buttons wrap on
    the narrow viewport;
  - the English pass showed `Edit`, `Use in execute`, `Node templates`,
    `Resume run`, `New run`, `Execute workflow` and the translated resume hint;
  - no browser page errors and no 404s in the fixture matrix.
- Published as `v0.1.0-beta.5` after a full-history rewrite removed the
  machine-specific Python path prefix from every reachable commit; the expanded
  audit reports `0` findings across all blobs and paths.
- A final working-tree scan for local paths, account names, school/student
  identifiers and tokens returned no hits. Two legacy handover/runtime command
  examples were normalized from a machine-specific Python path to `python`.
