import base64
from datetime import datetime
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blackboard_workbench.datasets import Datasets, read_table, parse_ontologies
from blackboard_workbench.custom_pipeline import evaluate_reference, mapper_class

ONTOLOGY = '''@prefix ex: <https://example.org/hr#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:Employee a owl:Class . ex:name a owl:DatatypeProperty; <http://www.w3.org/2000/01/rdf-schema#range> xsd:string .
ex:salary a owl:DatatypeProperty; <http://www.w3.org/2000/01/rdf-schema#range> xsd:decimal .
'''


def upload(name, data):
    return {'name': name, 'content': base64.b64encode(data.encode() if isinstance(data,str) else data).decode()}


def payload(reference=None):
    p={'table':upload('employees.csv','employee.name,salary\nAda,42000.5\nBen,51000.0\n'), 'ontologies':[upload('hr.ttl',ONTOLOGY)]}
    if reference is not None:p['reference']=upload('truth.json',json.dumps(reference))
    return p


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.datasets=Datasets(self.temp.name)

    def test_no_reference_means_no_benchmark_and_immutable_saved_rows(self):
        d=self.datasets.create({**payload(),'sample_rows':1})
        path,_=self.datasets.get(d['id'])
        self.assertFalse(d['benchmark_available']);self.assertFalse((path/'reference.json').exists())
        self.assertEqual((2,1), (d['row_count'],d['sample_rows']))
        self.assertEqual([{'employee.name':'Ada','salary':42000.5}],json.loads((path/'data.json').read_text()))
        self.assertEqual(d,self.datasets.list()[0])
        with self.assertRaises(ValueError):self.datasets.get('../outside')

    def test_partial_reference_resolves_namespace_and_rejects_unknown_columns(self):
        d=self.datasets.create(payload({'salary':{'class':'ex:Employee','property':'ex:salary'}}))
        path,_=self.datasets.get(d['id']);truth=json.loads((path/'reference.json').read_text())
        self.assertEqual(['salary'],d['reference_columns'])
        self.assertEqual('https://example.org/hr#salary',truth['salary']['property'])
        with self.assertRaises(ValueError):self.datasets.create(payload({'missing':{'class':'ex:Employee','property':'ex:name'}}))
        self.assertEqual(1,len(self.datasets.list()))

    def test_native_reference_format_is_supported(self):
        ref={'prefix':'@prefix ex: <https://example.org/hr#>.','mappings':{'salary':{'mapping':'ex:Employee ex:salary "salary".'}}}
        self.assertTrue(self.datasets.create(payload(ref))['benchmark_available'])

    def test_invalid_reference_and_ontology_are_not_saved(self):
        for body in [payload({}), payload({'salary':{'class':'ex:Employee','property':'ex:missing'}}),{**payload(),'ontologies':[upload('broken.ttl','not turtle')]}]:
            with self.subTest(body=body),self.assertRaises(ValueError):self.datasets.create(body)
        self.assertEqual([],self.datasets.list())

    def test_csv_preserves_codes_and_rejects_ambiguous_headers(self):
        t=read_table(upload('codes.csv','id,number,flag\n0010,10,true\n'))
        self.assertEqual({'id':'0010','number':10,'flag':True},t['data'][0])
        for content in ['a,a\n1,2\n','a,,c\n1,2,3\n','a\n1,2\n']:
            with self.assertRaises(ValueError):read_table(upload('bad.csv',content))

    def test_xlsx_sheet_selection_dates_and_formula_rejection(self):
        from openpyxl import Workbook
        wb=Workbook();wb.active.title='Ignore';wb.active.append(['other']);wb.active.append(['x'])
        sheet=wb.create_sheet('People');sheet.append(['name','joined']);sheet.append(['Ada',datetime(2025,1,2)])
        out=io.BytesIO();wb.save(out)
        table=read_table(upload('people.xlsx',out.getvalue()),'People')
        self.assertEqual(['Ignore','People'],table['sheets']);self.assertEqual('2025-01-02T00:00:00',table['data'][0]['joined'])
        sheet['B2']='=1+1';out=io.BytesIO();wb.save(out)
        with self.assertRaisesRegex(ValueError,'Formula'):read_table(upload('people.xlsx',out.getvalue()),'People')

    def test_invalid_workbook_returns_a_validation_error(self):
        with self.assertRaises(ValueError):read_table(upload('broken.xlsx',b'not an xlsx workbook'))

    def test_multiple_ontologies_and_conflicting_prefixes(self):
        more=ONTOLOGY.replace('ex:', 'other:').replace('https://example.org/hr#','https://example.org/other#')
        graph,sources=parse_ontologies([upload('a.ttl',ONTOLOGY),upload('b.ttl',more)])
        self.assertEqual(2,len(sources))
        self.assertIn('https://example.org/other#Employee',[str(s) for s in graph.subjects()])
        with self.assertRaisesRegex(ValueError,'prefix'):parse_ontologies([upload('a.ttl',ONTOLOGY),upload('b.ttl',ONTOLOGY.replace('https://example.org/hr#','https://example.org/other#'))])

    def test_benchmark_is_exact_and_only_scores_reference_columns(self):
        graph,_=parse_ontologies(payload()['ontologies'])
        truth={'salary':{'class':'https://example.org/hr#Employee','property':'https://example.org/hr#salary'}}
        candidates={'salary':[{'candidate':'ex:Employee ex:salary "salary".'}],'employee.name':[{'candidate':'ex:Employee ex:name "employee.name".'}]}
        self.assertIsNone(evaluate_reference(None,graph,{'mappings_candidates':candidates}))
        score=evaluate_reference(truth,graph,{'mappings_candidates':candidates})
        self.assertEqual(1,score['hits@1']);self.assertEqual({'salary':True},score['evaluations'])
        candidates['salary'][0]['candidate']='ex:Employee ex:name "salary".'
        self.assertEqual(0,evaluate_reference(truth,graph,{'mappings_candidates':candidates})['hits@1'])

    def test_validator_distinguishes_same_local_name_in_different_namespaces(self):
        graph,_=parse_ontologies(payload()['ontologies'])
        class Base:
            def __init__(self):
                self.name='employee.name';self.input_data={'json_data':[{'employee.name':'Ada'}]};self.logs={}
                self.state={'candidates':[{'candidate':'<https://wrong.org/Employee> ex:name "employee.name".','reason':'Wrong namespace'},{'candidate':'ex:Employee ex:name "employee.name".','reason':'Exact namespace'}]}
            def is_reasonable_for_range(self,values,rng):return values==['Ada'],'Values extracted'
            def _merge_matrix_rows(self,rows):self.state['matrix']=rows
        mapper=mapper_class(Base,graph)();mapper.validate_mappings()
        self.assertEqual(1,len(mapper.state['validated_candidates']))
        self.assertTrue(mapper.state['validated_candidates'][0]['candidate'].startswith('ex:Employee'))
