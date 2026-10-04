# Run your own table and ontology

Choose **Run your own data** in the sidebar. This uses Sebastian’s external SAST workflow with uploaded inputs; his bundled sample-ID workflow remains available.

1. Choose a CSV or XLSX file. The first row is the header. For XLSX, choose the worksheet. The preview shows the detected columns and up to five rows.
2. Choose how many example rows to send to the model, between 1 and 100 (default 20). All columns are mapped using those first rows. The file can contain up to 20,000 rows and 200 columns. The selected rows, metadata and ontologies are saved locally; the complete workbook is not retained. CSV must use UTF-8; comma, semicolon and tab separators are supported. Export Excel formulas as calculated values before upload.
3. Upload one to five Turtle (`.ttl`) ontologies. They must include classes (`owl:Class` or `rdfs:Class`) and datatype properties (`owl:DatatypeProperty`). Use distinct prefixes for distinct namespaces. Files are parsed and merged locally; remote `owl:imports` are not fetched, so upload imported definitions explicitly. The ontology terms keep their full namespace identities.
4. Optionally provide dataset/column descriptions and a reference-mapping JSON file.
5. Choose **Validate and save inputs**. This makes no model calls. Invalid tables, ontologies and reference mappings return an error before a dataset is saved.
6. Select a saved dataset, check the saved model connection and time limit, then choose **Start model run**. Follow Execution history and open the saved run when it finishes. For a large ontology, the model context window and time limit must be large enough; the earlier 95-minute VC-SLAM run is not a timing estimate for your dataset.

Each file is limited to 5 MB, and each HTTP request to 20 MB including base64 encoding. XLSX files may expand to at most 40 MB. Headers must be unique, nonempty and at most 200 characters; quotes, backslashes and control characters are rejected because the upstream representation uses column names as literal identifiers. Headers with spaces or dots remain flat column names; dots are not interpreted as nesting in custom tables. Empty cells become null. CSV numerical values are converted where unambiguous; leading-zero codes and long integer identifiers remain strings. Dates in Excel become ISO strings.

## Optional reference mappings

Use exact column names and full IRIs or prefixes declared in the uploaded ontologies:

```json
{
  "employeeName": {"class": "ex:Employee", "property": "ex:name"},
  "salary": {"class": "https://example.org/hr#Employee", "property": "https://example.org/hr#salary"}
}
```

Sebastian’s existing format is also supported:

```json
{
  "prefix": "@prefix ex: <https://example.org/hr#> .",
  "mappings": {
    "employeeName": {"mapping": "ex:Employee ex:name \"employeeName\" ."}
  }
}
```

References must point to an uploaded class and datatype property. Partial reference files are allowed: the benchmark explicitly reports its referenced-column scope. Columns without references are mapped and reviewable but do not enter the score denominator. An empty or malformed reference file produces a validation error; to run without references, leave that file input empty.

**No reference file means no benchmark.** The UI shows “No benchmark,” the saved result has `evaluation: null`, and no accuracy percentage or synthetic zero is produced. Review, discussion and exports remain available.

When references are supplied, exact class–property matches are scored before and after council reasoning. IRIs are resolved before comparison, so equivalent prefixes match and different namespaces remain different. Missing model mappings count as missing within the referenced-column denominator. Scores describe reference agreement, not proof that every alternative is semantically wrong.

Reference answers are stored separately and used only by the evaluator. They are never included in the original model prompts, historical examples, or later agent-review context. Documentation and example rows are model inputs; avoid putting the answer key there when evaluating.

## Integration boundary

The custom worker calls the pinned external `run_pipeline` with a generated local sample directory. The upstream checkout is not edited. A process-local compatibility layer preserves the generation, signal, selection and council flow while providing namespace-aware structural validation, exact extraction of flat spreadsheet headers, and optional reference evaluation. Uploaded inputs have no bundled historical examples. Dataset IDs and file hashes are recorded with the result.

These custom-input adaptations are additional execution conditions. A custom run is not a reproduction of the paper’s bundled benchmark. Existing imported outputs and sample-ID jobs keep their prior behavior.

## Downloadable example

Use the files in `examples/custom-data`: a small employee CSV, a Turtle ontology, and an optional reference JSON. Uploading and validating them is free of inference calls. Starting a run uses the model connection selected in Model settings.
