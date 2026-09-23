# Blackboard Workbench

A local review interface for [Sebastian Chmielewski's SAST-Blackboard](https://github.com/U0iS112/654321). This is a separate companion repository. It reads Sebastian's saved machine output, shows candidates, signal assessments and original council turns, and persists human comments and review decisions. It does not modify the original mapping result.

## Start with the synthetic example

Python 3.11+ is enough to view, import and review runs:

```sh
python3 -m blackboard_workbench.server --port 8031
```

Open <http://127.0.0.1:8031> and choose **Explore an example**. The example is explicitly synthetic; it is not a benchmark or live model result. Click `lat` to inspect the machine selection, candidate assessments and original council record. Add a reply or review decision, then reload to see that it persists.

Choose **Import SAST result** for a `*_mapping_results.json` exported by Sebastian's pipeline. The complete imported JSON is stored unchanged; the app derives IDs to link it with review events. If the import lacks original source documents, the interface makes that limitation visible.

The local database and job files live under `.workbench/`, which is ignored by Git. **Export review bundle** downloads the original machine output plus all saved posts, decisions and versions for archival or analysis. The exported bundle is not an import format. There are no user accounts or cloud sync.

## Run Sebastian's pipeline from the UI

Install the [original project's dependencies](https://github.com/U0iS112/654321/blob/main/requirements.txt) in a Python environment, then pass its checkout and Python executable:

```sh
python3 -m blackboard_workbench.server \
  --port 8031 \
  --upstream /path/to/654321 \
  --upstream-python /path/to/654321/.venv/bin/python
```

Set `OPENAIKEY` or `OPENAI_API_KEY` in the server environment, or use the original checkout's `env/.env`. The browser has no key form. Choose sample IDs, optional historical references, model and time limit. The worker calls Sebastian's original `run_pipeline` in a separate process and imports each result. It reads the original checkout but does not edit it. The job panel shows progress and supports cancellation. A provider may charge for calls made before cancellation. Live provider execution has not yet been verified for this companion app.

Only one model job runs at a time. A pipeline run is limited to five samples, 20 historical references and a 30–1800 second time limit. **Bounded agent review** in an attribute's Discussion tab runs a mapping assessor and challenger for one to three rounds (two to six calls). Their posts are advisory and may propose only a recorded validated candidate. A human makes the decision separately. This extra condition is distinct from the original SAST council method.

## Review a run

1. Select a saved run and an attribute.
2. Inspect the original machine mapping and each candidate's documentation, historical, value and proximity assessments.
3. Read the **Original council record**. In **Workspace discussion**, post questions, evidence and replies with optional candidate references.
4. Save a human decision with a reason: accept a validated candidate, reject or request further review. New decisions increment the version; earlier decisions stay in history.
5. Export the review bundle when you need an archival copy or want to analyze the full review record elsewhere.

A stale review decision is rejected and asks you to refresh. Names are self-declared, not authenticated identities. The machine output stays separate from all review events.

## Research boundary

| Available now | Still to develop and test |
| --- | --- |
| Saved runs, candidate/signal inspection, original council turns, persistent human discussion and versioned decisions | Generic adapters for RQ1 requirements or other task objects |
| Original SAST execution from a configured checkout | Continuous interactive blackboard scheduling |
| Bounded advisory review as a separate condition | Comparative evaluation of accuracy, harmful revisions, cost, speed and human usefulness |

The workbench makes decisions inspectable; it does not establish improved mapping accuracy. JEV is left for a later model comparison. See [architecture and adapter contract](docs/ARCHITECTURE.md).
