# Sebastian's original workflow in the workbench

This guide follows the implementation in [SAST-Blackboard](https://github.com/U0iS112/654321), specifically its [`run_pipeline` entry point](https://github.com/U0iS112/654321/blob/074ddfc409bdd120c93a0b68773bafa464e56504/blackboard/codebase/core/blackboard_semantic_mapping.py). The workbench invokes that function and displays its saved result. Mapping generation, signal assessments, initial selection, and the original council remain Sebastian's code.

## Input to output

For each selected four-digit sample ID, Sebastian's pipeline reads a sample under `datacorpus/vcslam/<id>/`:

| Source | Use in the original pipeline |
| --- | --- |
| `<id>_samples.json` | Input JSON whose leaf paths become attributes to map |
| `<id>.txt` | Optional textual documentation supplied as mapping context |
| `<id>_unmapped.json` | Optional paths excluded from mapping |
| `<id>_mapped.json` | Reference mappings used by the pipeline's before/after evaluation |
| `datacorpus/vcslam/ontology/ontology.ttl` | Ontology used to form and validate mapping candidates |
| Historical sample IDs | Earlier sample data, documentation, unmapped paths, and mappings supplied as precedent |

The selected model and provider credential are used by Sebastian's agents. The workbench's job controls pass those inputs to his pipeline and set an output directory in the workbench data volume. The upstream checkout is read-only at runtime; results are not written back into it.

The pipeline saves one `<id>_mapping_results.json` per processed sample. Its main fields are `attributes` (candidate states, selected mapping, matrix, and processing logs), `discussions` (the original council), `reasoning_effect` (mapping changes across council reasoning), and `evaluation` (before/after comparison with reference mappings).

## What happens during a SAST run

| Original stage | What Sebastian's code does | Where to inspect it in the UI |
| --- | --- | --- |
| Load sample and historical context | Reads sample JSON, documentation, ontology, reference mapping, and selected historical examples. Leaf paths become attributes; paths listed as unmapped are excluded. | Select the saved run, then an attribute. Expand **Available source context** in **Candidates & signals** for runs started from this workbench. |
| Generate candidates | `AttributeMapper.generate_mappings` proposes ontology mapping triples for each attribute. | Expand **Original matrix and processing logs** to see the full saved state and logs. |
| Validate candidates | `AttributeMapper.validate_mappings` checks proposed mappings and saves the validated candidate list. | **Validated candidates** lists each recorded candidate. Open **Complete candidate record** for its full data. |
| Assess signals | Agents evaluate documentation, historical precedent, example values, and proximity between the attribute name and mapping. | Each candidate card shows the saved signal votes and reasons. The original matrix and logs provide more detail. |
| Select an initial mapping | `select_final_mappings` chooses a mapping from validated candidates, or leaves no final mapping if none was selected. | **Original machine selection** shows the final mapping saved after the full pipeline; the matrix and logs expose the selection record. |
| Check consistency and run the original council | `ReasoningAgent.determine_discussions` identifies groups of related attributes to discuss. `DiscussionEngine.run_discussion` records bounded turns and may apply commands that revise mappings. | **Discussion → Original council record** shows a council discussion when the selected attribute participated. Expand a turn or the full record. |
| Compare before and after | The pipeline compares selected mappings with the sample's reference mappings before and after council reasoning and records any changed selections. | Expand **Run-level evaluation and changes** under **Candidates & signals**. |
| Save the result | Writes `*_mapping_results.json`. | The workbench imports it as a saved run. **Export review bundle** later includes this machine result and workbench review records. |

**Original machine selection** in the main card is the pipeline's saved final mapping, after any council changes. For the earlier selection and the effects of council reasoning, inspect the original matrix/logs and the run-level `reasoning_effect` field. An attribute without an original council entry simply had no saved council discussion involving it.

## How the UI adds review

The workbench stores the imported machine result and derives stable IDs for each attribute and validated candidate. It shows the original result without letting a reviewer rewrite it. For a run started through the UI, it also attaches source context such as the sample JSON, documentation, model, historical IDs, and upstream revision to make the result easier to inspect. When you import a standalone `*_mapping_results.json` manually, that extra source context may be absent; the interface says so.

The three attribute tabs serve different purposes:

- **Candidates & signals** presents Sebastian's saved candidate list, votes, final mapping, matrix, logs, evaluations, and available source context.
- **Discussion** presents Sebastian's original council turns first. Beneath them, **Workspace discussion** stores new human posts and replies. Its optional **bounded agent review** adds advisory workbench posts and is a separate process from the original council.
- **Decision history** shows the unchanged machine selection alongside a separate, versioned human decision record.

A human can accept one recorded validated candidate, reject the mapping, or request further review. A saved decision does not rerun Sebastian's agents or overwrite their output. This separation makes it possible to compare machine reasoning and subsequent human judgment.

For operation and updates, see the [README](../README.md). For data storage and the adapter contract, see [Architecture](ARCHITECTURE.md).
