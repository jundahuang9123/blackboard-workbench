# Model connections

The **Model settings** button in the sidebar opens the connection panel. One saved connection is used for newly started SAST pipeline jobs and optional bounded agent reviews. Saved runs, human discussions, and human decisions work without a model connection.

## Cloud connection

1. Select a provider and choose a suggested **Model**, or enter a model ID available to your provider account. Presets are editable suggestions; account access is still required.
2. Enter that provider's **API key** in the password field. Leave **Remember key on this Mac** unchecked for a key that lasts only until the workbench server restarts.
3. Select **Save settings**. A blank key field keeps an existing key while applying your storage choice: check **Remember key on this Mac** to save a session key, or uncheck it to move a remembered key into this session only. A key from the server environment is not copied to the credential file unless you enter it explicitly. The panel displays where the key comes from.
4. Select **Test connection · 1 request**. This sends one short JSON inference request to the saved connection, which may incur a cloud charge. Resolve any connection, permission, quota, or JSON response error before starting a full run.
5. Close the panel, expand **Run Sebastian's pipeline**, enter sample `0044`, and leave historical IDs blank. For the tested local 27B setup, set the time limit to `7200`; choose a limit appropriate to other models. Select **Start model run**, then follow **Execution history** and **Open saved run** after completion.

The short test verifies only connectivity and a tiny JSON response. It does not test the full ontology prompts, sample parsing, candidate generation, signals, or council. A full local sample `0044` run completed through Docker Compose with Ollama 0.35.1 and `blackboard-qwen27b:latest` (Qwen3.5 27B Q4_K_M, 65,536 context tokens, thinking off). It took about 95 minutes; the built-in evaluation found 0/4 exact reference matches before and after the original council. This verifies the software path for that one setup while showing that format compliance and completion do not imply mapping accuracy. No cloud inference call has been verified.

| Provider | Fixed official API address | Suggested model IDs |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-5`, `gpt-5-mini`, `gpt-5-nano` |
| Anthropic · Claude | `https://api.anthropic.com/v1` | `claude-sonnet-5`, `claude-haiku-4-5-20251001`, `claude-opus-5-5` |
| Google · Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview` (preview) |
| Mistral | `https://api.mistral.ai/v1` | `mistral-small-2603`, `mistral-medium-3-5`, `mistral-large-2512` |

OpenAI's GPT-5 preset retains the original workflow's model choice. Other selections are distinct execution conditions, including the adapter's alternate-provider output-token bounds; they are not claims of equivalent mapping accuracy. The adapter preserves Sebastian's text chat contract. Claude's OpenAI compatibility does not enforce `response_format`; JSON is requested through prompts and checked by the consuming operation. Local model output also needs validation. Changing provider does not change the upstream algorithm or prompts into a provider-specific implementation.

Official references: [OpenAI model catalog](https://platform.openai.com/docs/models), [Claude compatibility](https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk) and [models](https://platform.claude.com/docs/en/models/overview), [Gemini compatibility](https://ai.google.dev/gemini-api/docs/openai) and [models](https://ai.google.dev/gemini-api/docs/models), [Mistral compatibility](https://docs.mistral.ai/resources/migration-guides) and [models](https://docs.mistral.ai/models). Catalog availability changes; enter a newer supported ID when needed and test it before running the pipeline.

## Keys and local storage

A UI key is sent to the workbench server and held in memory by default. Selecting **Remember key on this Mac** and saving stores a newly entered or existing UI session key in `credentials.json` in the workbench data directory, with owner-only permissions (`0600`). Unchecking the option and saving moves a remembered key into session memory and removes its stored copy; re-entering the key is not required. Environment keys are not persisted by this checkbox unless entered explicitly. In Docker Compose this is `/var/lib/blackboard-workbench/credentials.json` inside the persistent `workbench_data` volume. **The file is plaintext, not encrypted**; filesystem permissions do not protect it from the host administrator or a volume backup. The checkbox is optional and must be selected deliberately.

Public settings responses expose key status, never the key. The UI clears the input after saving and does not use browser storage for credentials. Keys are absent from job configuration files and review bundles. The job's provider, model, and endpoint are recorded; the key is passed privately to its worker environment. **Remove key** removes the UI session/saved key for that provider. It cannot remove a credential set in the server environment, and it does not erase a key already held by an executing worker.

For environment configuration, copy `.env.example` to `.env` and set the appropriate variable: `OPENAIKEY` or `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `MISTRAL_API_KEY`. Restart with `docker compose up -d` after changing environment credentials. Never commit `.env`. A UI session key takes precedence over a remembered key, then the server environment.

## Ollama on the Mac

Install and start [Ollama](https://docs.ollama.com/quickstart), then download a model, for example:

~~~sh
ollama pull llama3.1:8b
~~~

The UI also suggests `qwen3.5:9b` and `gemma3:12b`; these are examples that must be installed first. Use **Local · Ollama**, then **Load available models** to obtain the IDs your server advertises. Select one, save the settings, and run the short connection test.

Ollama's native local default is `http://localhost:11434/v1`; local requests normally need no API key. The Compose UI defaults to `http://host.docker.internal:11434/v1` because container localhost refers to the container. The workbench does not run `ollama pull` or start Ollama for you. See [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) and [authentication](https://docs.ollama.com/api/authentication).

## LM Studio or another local server

In [LM Studio](https://lmstudio.ai/docs/developer/core/server), download/load a chat model and start the API server from the **Developer** tab. Choose **Local · LM Studio / compatible server** in the workbench. Its Compose default is `http://host.docker.internal:1234/v1`; native LM Studio commonly uses `http://localhost:1234/v1`. For another OpenAI-compatible runtime, enter its reachable private server address ending in `/v1`.

Use **Load available models**, enter an advertised ID, save, and test. LM Studio does not require authentication by default. If you enabled its authentication setting or your local gateway requires a token, enter that token in the optional API-key field and retain the server's protection. See [chat compatibility](https://lmstudio.ai/docs/developer/openai-compat/chat-completions), [structured output](https://lmstudio.ai/docs/developer/openai-compat/structured-output), and [authentication](https://lmstudio.ai/docs/developer/core/authentication). Model listing is not proof that the runtime can load a model or complete a prompt.

## Local reachability and context

The local server must accept connections from the workbench container. `host.docker.internal` resolves the Docker host; it does not change a server's listening interface or access rules. If a server restricted to host loopback is unreachable, configure a controlled Docker-to-host endpoint or private host-side forwarding appropriate to your setup. Keep access restricted to the intended local/container path and preserve authentication. Do not expose the model server publicly to make a connection test pass. The workbench accepts private, localhost, and Docker-host addresses for local profiles.

The pinned VC-SLAM ontology alone is about 198 KB, before sample data, historical examples, and agent instructions. Bytes are not tokens, and the short test is much smaller. Configure enough model context for the complete requests; a small or short-context local model may pass the test and fail the pipeline. Ollama's OpenAI-compatible API does not set context size: configure `num_ctx` through an Ollama model definition and use that model's ID. LM Studio context is configured when loading the model. Increasing the workbench time limit does not enlarge a model's context window.

For the pipeline-to-UI correspondence, see [Sebastian's original workflow](ORIGINAL_WORKFLOW.md). For process isolation and data provenance, see [Architecture](ARCHITECTURE.md).

Local model requests allow up to 900 seconds for loading and long-prompt processing; cloud requests allow 90 seconds. The overall job time limit still applies and cancellation stops the worker.

The **Ollama thinking** selector offers **Model default** or **Off · direct answers**. Off sends `reasoning_effort: "none"` through Ollama’s compatible API, which requests disabled thinking for supported models such as Qwen3.5. This can reduce response time; it is not a claim of equal accuracy. The setting is saved per provider and recorded in job metadata, imported pipeline context, and agent-review provenance. See [Ollama thinking controls](https://docs.ollama.com/api/openai-compatibility).

For long local runs the overall job limit can be set up to 7,200 seconds; cloud runs remain bounded to 1,800 seconds. The 27B model can take several minutes to process each full-ontology prompt. Ollama requests use an object-or-array JSON schema and are parsed before passing responses to the upstream pipeline. Malformed JSON fails the job instead of silently reaching upstream fallback logic. This constrains syntax, not mapping correctness; it does not repair model responses. The `object-or-array-v1` format condition is recorded with jobs and exports.
