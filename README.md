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

To run the pipeline with a model, open **Model settings** in the sidebar. Choose **OpenAI**, **Anthropic · Claude**, **Google · Gemini**, **Mistral**, **Local · Ollama**, or **Local · LM Studio / compatible server**. Choose a suggested model or enter an exact model ID, enter a provider key when required, and select **Save settings**, then **Test connection · 1 request**. The test makes one short inference request and checks its JSON response; it does not prove that the full pipeline's larger prompts will succeed. Cloud requests may incur provider charges.

Keys entered in the UI last until the server restarts by default. **Remember key on this Mac** explicitly saves the key in a local file with owner-only permissions; **the file is plaintext, not encrypted**. In Compose, this file is inside the persistent data volume. Keys are not saved in browser storage or exported review bundles. Environment-file configuration remains available. See [model connections, key storage, and local model setup](docs/MODEL_CONNECTIONS.md).

For a local model, start its server and download/load a model before connecting the workbench. **Load available models** retrieves the exact IDs advertised by that server. Docker's default addresses use `host.docker.internal` to reach a model server on the Mac; they require a reachable, controlled Docker-to-host connection. The workbench does not install or start the model runtime.

Useful commands:

~~~sh
docker compose logs -f workbench
docker compose ps
docker compose down
~~~

Runs, posts, decisions, and job logs live in the Compose-managed `workbench_data` volume. `docker compose down` keeps that volume; `docker compose down -v` deletes it.

## Run your own data

Choose **Run your own data** in the sidebar to upload a CSV or XLSX table, select a worksheet, and add one or more Turtle ontologies. Preview the columns and example rows, optionally add descriptions and reference mappings, then choose **Validate and save inputs**. Select the saved dataset and **Start model run** using your configured model connection.

Reference mappings are optional. **Without a reference file, the run has no benchmark score**; mappings remain available for inspection, discussion and human review. With references, the UI reports exact class–property matches over the supplied reference columns. Reference answers are kept separate from model prompts. See [input formats, limits and examples](docs/CUSTOM_DATA.md).

## Run Sebastian's pipeline

In the sidebar, expand **Run Sebastian's pipeline**. The available four-digit sample IDs come from the pinned repository's `datacorpus/vcslam` directory. The selected connection appears above the run button. Enter one or more sample IDs, optional historical sample IDs, and a time limit, then select **Start model run**.

For a first complete run:

1. Save a model connection and pass **Test connection · 1 request** first.
2. Expand **Run Sebastian's pipeline** and set **Sample IDs** to `0044`.
3. Leave **Historical sample IDs** blank. For the tested local `blackboard-qwen27b:latest` model, set **Time limit (seconds)** to `7200`; other connections need a limit appropriate to their runtime.
4. Select **Start model run** and follow **Execution history**. After completion, choose **Open saved run**.

A complete local run of sample `0044` finished on 4 October 2026 with Ollama 0.35.1 and Qwen3.5 27B Q4_K_M, configured with 65,536 context tokens and thinking off. It took about 95 minutes and produced four attributes and one original council discussion. The built-in reference evaluation was **0/4 exact matches**, both before and after council reasoning. This verifies execution and UI import for that configuration, not mapping quality or other providers. The labeled synthetic example and importing existing results work without a key.

The workbench calls Sebastian's original `run_pipeline` in a child process. It supplies the selected sample and historical IDs, the saved model connection, and a writable output directory. A process-local client adapter routes model requests while leaving Sebastian's source unchanged. Sebastian's code reads the sample JSON, documentation, reference mapping, ontology, and historical examples from its own checkout. It generates and validates mapping candidates, records signal assessments, chooses initial mappings, runs its selective council discussions, and writes `*_mapping_results.json`. The workbench imports those saved results as runs.

The interface limits each request to five samples and 20 historical IDs. Job limits are 30–1800 seconds for cloud models and 30–7200 seconds for local models. One model job runs at a time. **Execution history** shows status, worker logs, and a cancel control. Cancellation stops the local worker, but cannot undo provider usage already incurred. Use **Open saved run** when a job completes.

## Inspect and review a run

1. Select a saved run in the sidebar and choose an attribute from the queue. Search by attribute name or filter by human review status.
2. In **Candidates & signals**, compare the machine's selected mapping with validated candidates. Read the documentation, historical, example-value, and name-proximity assessments. Expand the complete candidate record, original matrix and logs, run-level evaluation, or available source context when needed.
3. In **Discussion**, open the **Original council record** for any discussion involving that attribute. This is Sebastian's bounded council output from the SAST run. **Workspace discussion** below it holds later human posts, replies, and optional candidate references.
4. Use **Record your review** to accept a recorded candidate, reject the mapping, or mark it for further review. Add a reason. **Decision history** preserves every saved human decision and shows the current one beside the unchanged machine result.
5. Use **Export review bundle** to download the machine output together with posts, decisions, and versions. This archival bundle is not an import format.

A “validated candidate” passed Sebastian's candidate validation step; it is not human approval or proof of semantic correctness. If an attribute has no validated candidates, it cannot be accepted. A stale review is rejected so the reviewer can refresh before saving. Reviewer names are self-declared; this is a local interface without accounts or shared authentication.

**Request bounded agent review** in the Discussion tab is an additional workbench action, distinct from Sebastian's original council. A mapping assessor and challenger can add advisory posts for one to three rounds (two to six model calls). They may propose only a candidate already recorded for that attribute. They cannot change the original machine mapping or save a human decision.

## Adopt a later Sebastian revision

The default `SAST_REF` in [`compose.yaml`](compose.yaml) and [`.env.example`](.env.example) pins the [development fork of Sebastian's repository](https://github.com/jundahuang9123/profile-requirements-extraction/tree/shared-ontology-context) to commit `9f637920e9cf8e1ceaa63556105959a46d4d0ebc`. This makes each image's pipeline version explicit. When Sebastian publishes an optimization, set `SAST_REPO` and `SAST_REF` in your local `.env` to its repository and reviewed commit SHA, then rebuild and restart:

~~~sh
docker compose up --build -d
~~~

The Docker build checks out that commit. It installs the pipeline packages listed in [`requirements-upstream-runtime.txt`](requirements-upstream-runtime.txt), which match the imports used at the default pinned revision. When adopting a later commit, review its `requirements.txt` and imports and update this list if needed. New code becomes available to the workbench without copying it here, provided its `run_pipeline` call and `*_mapping_results.json` output remain compatible. Check **Execution history** for the upstream revision used by a run, then verify an example pipeline result and its candidate/council views after updating. If Sebastian changes those interfaces, update the workbench adapter and worker for the new contract.

The UI stores the original output and review events separately. It does not claim to improve mapping accuracy by itself. A different provider/model and the adapter's output-token bounds are separate execution conditions, not evidence of equivalent accuracy. Provider routing and the UI have offline checks. The complete local `0044` pipeline run with Ollama 0.35.1 and `blackboard-qwen27b:latest` completed, but its built-in evaluation was 0/4 exact matches. Cloud inference and other local models remain unverified; do not treat a short connection test as evidence of mapping quality. See [architecture and data boundaries](docs/ARCHITECTURE.md).


### Shared ontology context proposal

The default Docker dependency is the development branch described in [Architecture](docs/ARCHITECTURE.md#proposed-shared-ontology-dependency), pinned to a full commit SHA. It has not been submitted as an upstream pull request. In **Run Sebastian's pipeline** or **Run your own data**, select **Shared context** to place a stable ontology prefix on generation and documentation requests, or **Legacy** for the original prompt layout. Signals, selection and councils keep their compact inputs. Server-side reuse is not guaranteed. Execution history records the choice. Custom uploads still accept one to five Turtle ontologies and an optional reference file; without a reference, benchmarking remains disabled.

The first shared-context run added expensive full-ontology inputs to compact signals and was slower on local Qwen. The current pin corrects that regression while preserving the same model configuration and agent workflow. Offline routing and pipeline tests pass; the corrected layout has not yet had a live timing comparison. See the [upstream correction and limitations](https://github.com/jundahuang9123/profile-requirements-extraction/blob/9f637920e9cf8e1ceaa63556105959a46d4d0ebc/docs/SHARED_ONTOLOGY_CONTEXT.md#controlled-correction-for-local-qwen).

To change the source after an upstream optimization is reviewed, set `SAST_REPO` and `SAST_REF` when building Compose. Keep the source URL and reviewed full commit together; an older upstream commit without the `context_mode` API requires the older workbench worker as well. Updating the pin alone does not establish benchmark equivalence.
