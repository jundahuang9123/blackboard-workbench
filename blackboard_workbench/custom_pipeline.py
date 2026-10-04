"""Custom-input compatibility layer around the pinned, external SAST pipeline."""
import json
from pathlib import Path
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, OWL, XSD


def evaluate_reference(reference, graph, to_evaluate):
    """Exact full-IRI class/property matching over only the supplied reference columns."""
    if reference is None:
        return None
    prefix = ''.join(f'@prefix {p}: <{u}> .\n' for p, u in graph.namespaces())
    evaluations, errors = {}, []
    for column, expected in reference.items():
        candidates = to_evaluate['mappings_candidates'].get(column, [])
        if not candidates:
            evaluations[column] = None
            continue
        try:
            parsed = Graph().parse(data=prefix + candidates[0]['candidate'], format='turtle')
            if len(parsed) != 1:
                raise ValueError()
            subject, predicate, _ = next(iter(parsed))
            evaluations[column] = str(subject) == expected['class'] and str(predicate) == expected['property']
        except Exception:
            evaluations[column] = False
            errors.append(column)
    return {'hits@1': sum(v is True for v in evaluations.values()),
            'not_hits@1': sum(v is False for v in evaluations.values()),
            'no_mappings_provided': sum(v is None for v in evaluations.values()),
            'evaluations': evaluations, 'errors': errors}


def mapper_class(base, graph):
    """Retain upstream generation/signals; resolve custom namespaces and flat column keys exactly."""
    prefix = ''.join(f'@prefix {p}: <{u}> .\n' for p, u in graph.namespaces())
    class CustomMapper(base):
        def _extract_values_for_attribute(self, json_data, attribute_path):
            # Spreadsheet headers containing dots are flat names, not JSON paths.
            if isinstance(json_data, list) and all(isinstance(r, dict) for r in json_data):
                return [r[attribute_path] for r in json_data if attribute_path in r]
            return super()._extract_values_for_attribute(json_data, attribute_path)

        def validate_mappings(self):
            validated, rows, logs = [], [], []
            for entry in self.state.get('candidates') or []:
                candidate = entry['candidate']
                meta = {'candidate': candidate, 'reason': entry.get('reason', ''), 'rdf_syntax_ok': False,
                        'subject_in_ontology': False, 'predicate_in_ontology': False,
                        'predicate_is_datatype_property': False, 'range_check': {'ok': False},
                        'accepted_by_validator': False}
                try:
                    parsed = Graph().parse(data=prefix + candidate, format='turtle')
                    if len(parsed) != 1:
                        raise ValueError()
                    subject, predicate, obj = next(iter(parsed))
                    meta['rdf_syntax_ok'] = isinstance(subject, URIRef) and isinstance(predicate, URIRef) and isinstance(obj, Literal) and str(obj) == self.name
                    meta['subject_in_ontology'] = (subject, RDF.type, OWL.Class) in graph or (subject, RDF.type, RDFS.Class) in graph
                    datatype = (predicate, RDF.type, OWL.DatatypeProperty) in graph
                    meta['predicate_in_ontology'] = datatype or (predicate, RDF.type, OWL.ObjectProperty) in graph
                    meta['predicate_is_datatype_property'] = datatype
                    rng = next(graph.objects(predicate, RDFS.range), None)
                    range_name = 'xsd:' + str(rng)[len(str(XSD)):] if rng and str(rng).startswith(str(XSD)) else str(rng) if rng else None
                    values = self._extract_values_for_attribute(self.input_data['json_data'], self.name)
                    ok, details = self.is_reasonable_for_range(values, range_name) if datatype else (False, 'Object properties cannot map literal column values')
                    meta['range_check'] = {'range_iri': range_name, 'ok': ok, 'details': details}
                    meta['accepted_by_validator'] = all(meta[k] for k in ['rdf_syntax_ok','subject_in_ontology','predicate_in_ontology','predicate_is_datatype_property']) and ok
                except Exception:
                    meta['error'] = 'Candidate is not a single valid mapping triple.'
                if meta['accepted_by_validator']:
                    validated.append({'candidate': candidate, 'reason': entry.get('reason', ''), 'validator_meta': meta})
                rows.append({'candidate': candidate, 'agents': {'validator': {'accepted': meta['accepted_by_validator'], 'reason': meta}}})
                logs.append(meta)
            self.state['validated_candidates'] = validated
            self._merge_matrix_rows(rows)
            self.logs['validate_mappings'] = {'per_candidate': logs}
    return CustomMapper


def run_custom_pipeline(pipeline, cfg):
    dataset = Path(cfg['dataset_path'])
    metadata = json.loads((dataset/'metadata.json').read_text())
    data = json.loads((dataset/'data.json').read_text())
    ontology = (dataset/'ontology.ttl').read_text()
    documentation = (dataset/'documentation.txt').read_text()
    ref_path = dataset/'reference.json'
    reference = json.loads(ref_path.read_text()) if ref_path.exists() else None
    graph = Graph().parse(data=ontology, format='turtle')
    input_dir = Path(cfg['output']).parent/'custom-input'
    sample_dir = input_dir/'0000'
    sample_dir.mkdir(parents=True)
    (input_dir/'ontology').mkdir()
    (input_dir/'ontology'/'ontology.ttl').write_text(ontology)
    (sample_dir/'0000_samples.json').write_text(json.dumps(data, ensure_ascii=False))
    (sample_dir/'0000.txt').write_text(documentation)
    # Ground truth is used only in the evaluator closure. It is never written
    # into pipeline sample inputs, historical examples or model prompt context.
    (sample_dir/'0000_mapped.json').write_text('{}')
    pipeline.AttributeMapper = mapper_class(pipeline.AttributeMapper, graph)
    pipeline.evaluate_top_k = lambda *, k, reference_model, to_evaluate: evaluate_reference(reference, graph, to_evaluate)
    print(f'Custom dataset: {metadata["title"]} · {len(metadata["columns"])} columns · {len(data)} example rows', flush=True)
    print('Reference benchmark enabled.' if reference is not None else 'No reference mappings supplied. Benchmark disabled.', flush=True)
    pipeline.run_pipeline(str(input_dir), ['0000'], [], cfg['output'], False)
    for result in Path(cfg['output']).glob('*/*/*_mapping_results.json'):
        raw = json.loads(result.read_text())
        if reference is None:
            raw['evaluation'] = None
        raw['benchmark'] = {'available': reference is not None, 'reference_columns': list(reference) if reference else [],
                            'reason': 'Exact class/property matching over supplied reference columns.' if reference else 'No reference mappings supplied.'}
        raw['workbench_context'] = {'data': data, 'documentation': documentation, 'historical_ids': [],
                                    'dataset': metadata, 'upstream_revision': cfg.get('upstream_revision'),
                                    **cfg['llm'], 'json_output': cfg.get('json_output')}
        result.write_text(json.dumps(raw, indent=2, ensure_ascii=False))
