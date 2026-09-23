# Blackboard Workbench

A browser workbench for [Sebastian Chmielewski's SAST-Blackboard](https://github.com/U0iS112/654321). It can run Sebastian's semantic-typing pipeline, inspect the resulting attribute mappings and council discussions, and keep human review alongside the original machine result.

Sebastian's source is an external build dependency. The container retrieves a **pinned commit** of his repository and runs its existing `run_pipeline` function. The workbench does not vendor or rewrite that pipeline. See [how the original workflow appears in the UI](docs/ORIGINAL_WORKFLOW.md).

## Start with Docker Compose

Install Docker with the Compose plugin, then:

~~~sh
git clone https://github.com/jundahuang9123/blackboard-workbench.git
cd blackboard-workbench
docker compose up --build -d
~~~

Open [http://127.0.0.1:8031](http://127.0.0.1:8031). Choose **Explore an example** to inspect a clearly labeled synthetic run, or **Import SAST result** to load an existing `*_mapping_results.json` file. Neither action makes model calls. The first build fetches Sebastian's pinned source and installs the packages required by this pipeline path. It may take time.

To start a live SAST run, put your provider key in the local Compose environment file:

~~~sh
cp .env.example .env
~~~

Edit `.env` and set `OPENAIKEY`. `OPENAI_API_KEY` is also accepted by the worker. Restart the service after changing the key:

~~~sh
docker compose up -d
~~~

The key is read by the server process; the browser has no key field. Live runs call the configured provider and may incur charges. They have not yet been verified end to end in this container setup.

Useful commands:

~~~sh
docker compose logs -f workbench
docker compose ps
docker compose down
~~~

Runs, posts, decisions, and job logs live in the Compose-managed `workbench_data` volume. `docker compose down` keeps that volume; `docker compose down -v` deletes it.

## Run Sebastian's pipeline

In the sidebar, expand **Run Sebastian's pipeline**. The available four-digit sample IDs come from the pinned repository's `datacorpus/vcslam` directory. Enter one or more sample IDs, optional historical sample IDs, a model identifier, and a time limit, then select **Start model run**.

The workbench calls Sebastian's original `run_pipeline` in a child process. It supplies the selected sample and historical IDs, the model name, and a writable output directory. Sebastian's code reads the sample JSON, documentation, reference mapping, ontology, and historical examples from its own checkout. It generates and validates mapping candidates, records signal assessments, chooses initial mappings, runs its selective council discussions, and writes `*_mapping_results.json`. The workbench imports those saved results as runs.

The interface limits each request to five samples, 20 historical IDs, and 30–1800 seconds. One model job runs at a time. **Execution history** shows status, worker logs, and a cancel control. Cancellation stops the local worker, but cannot undo provider usage already incurred. Use **Open saved run** when a job completes.

## Inspect and review a run

1. Select a saved run in the sidebar and choose an attribute from the queue. Search by attribute name or filter by human review status.
2. In **Candidates & signals**, compare the machine's selected mapping with validated candidates. Read the documentation, historical, example-value, and name-proximity assessments. Expand the complete candidate record, original matrix and logs, run-level evaluation, or available source context when needed.
3. In **Discussion**, open the **Original council record** for any discussion involving that attribute. This is Sebastian's bounded council output from the SAST run. **Workspace discussion** below it holds later human posts, replies, and optional candidate references.
4. Use **Record your review** to accept a recorded candidate, reject the mapping, or mark it for further review. Add a reason. **Decision history** preserves every saved human decision and shows the current one beside the unchanged machine result.
5. Use **Export review bundle** to download the machine output together with posts, decisions, and versions. This archival bundle is not an import format.

A “validated candidate” passed Sebastian's candidate validation step; it is not human approval or proof of semantic correctness. If an attribute has no validated candidates, it cannot be accepted. A stale review is rejected so the reviewer can refresh before saving. Reviewer names are self-declared; this is a local interface without accounts or shared authentication.

**Request bounded agent review** in the Discussion tab is an additional workbench action, distinct from Sebastian's original council. A mapping assessor and challenger can add advisory posts for one to three rounds (two to six model calls). They may propose only a candidate already recorded for that attribute. They cannot change the original machine mapping or save a human decision.

## Adopt a later Sebastian revision

The default `SAST_REF` in [`compose.yaml`](compose.yaml) and [`.env.example`](.env.example) pins [Sebastian's repository](https://github.com/U0iS112/654321) to commit `074ddfc409bdd120c93a0b68773bafa464e56504`. This makes each image's pipeline version explicit. When Sebastian publishes an optimization, set `SAST_REF` in your local `.env` to the reviewed commit SHA, then rebuild and restart:

~~~sh
docker compose up --build -d
~~~

The Docker build checks out that commit. It installs the pipeline packages listed in [`requirements-upstream-runtime.txt`](requirements-upstream-runtime.txt), which match the imports used at the default pinned revision. When adopting a later commit, review its `requirements.txt` and imports and update this list if needed. New code becomes available to the workbench without copying it here, provided its `run_pipeline` call and `*_mapping_results.json` output remain compatible. Check **Execution history** for the upstream revision used by a run, then verify an example pipeline result and its candidate/council views after updating. If Sebastian changes those interfaces, update the workbench adapter and worker for the new contract.

The UI stores the original output and review events separately. It does not claim to improve mapping accuracy by itself. See [architecture and data boundaries](docs/ARCHITECTURE.md).
