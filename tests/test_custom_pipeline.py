"""Exercise the real pinned SAST workflow offline when its checkout is available."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from blackboard_workbench.custom_pipeline import run_custom_pipeline
from blackboard_workbench.datasets import Datasets
from blackboard_workbench.store import Store
from test_datasets import payload


@unittest.skipUnless(os.environ.get('SAST_UPSTREAM'), 'Set SAST_UPSTREAM to the pinned upstream checkout for integration tests.')
class CustomPipelineTests(unittest.TestCase):
    def test_real_pipeline_imports_with_and_without_reference_without_model_calls(self):
        sys.path.insert(0,os.environ['SAST_UPSTREAM'])
        from blackboard.codebase.core import blackboard_semantic_mapping as pipeline
        base=pipeline.AttributeMapper
        def generate(mapper,*args,**kwargs):
            prop='name' if mapper.name=='employee.name' else 'salary'
            mapper.state['candidates']=[{'candidate':f'ex:Employee ex:{prop} "{mapper.name}".','reason':'Offline test fixture'}]
        def select(mapper):
            mapper.state['final_mapping']={'candidate':mapper.state['validated_candidates'][0]['candidate'],'meta':mapper.state['validated_candidates'][0],'score':1}
        for with_reference in [False,True]:
            with self.subTest(with_reference=with_reference),tempfile.TemporaryDirectory() as tmp:
                data=payload({'salary':{'class':'ex:Employee','property':'ex:salary'}} if with_reference else None)
                datasets=Datasets(tmp);meta=datasets.create(data);folder,_=datasets.get(meta['id'])
                out=Path(tmp)/'output';out.mkdir()
                cfg={'dataset_path':str(folder),'output':str(out),'llm':{'model':'offline-fixture','provider':'local','endpoint':'http://localhost:1234/v1','thinking':'default'}}
                with patch.dict(os.environ,{'OPENAIKEY':'offline-not-a-key'}),patch.object(base,'generate_mappings',generate),patch.object(base,'select_final_mappings',select),patch.object(base,'_call_llm_as_json',return_value=[{'accepted':True,'reason':'Offline fixture','score':3}]),patch.object(pipeline.ReasoningAgent,'determine_discussions',return_value={}),patch.object(pipeline,'AttributeMapper',base),patch.object(pipeline,'evaluate_top_k',pipeline.evaluate_top_k):
                    run_custom_pipeline(pipeline,cfg)
                raw=json.loads(next(out.glob('*/*/*_mapping_results.json')).read_text())
                self.assertEqual(2,len(raw['attributes']))
                self.assertEqual(with_reference,raw['benchmark']['available'])
                self.assertNotIn('reference.json',json.dumps(raw['workbench_context']))
                if with_reference:
                    self.assertEqual(1,raw['evaluation']['after_reasoning']['hits@1'])
                    self.assertEqual({'salary':True},raw['evaluation']['after_reasoning']['evaluations'])
                else:self.assertIsNone(raw['evaluation'])
                run=Store(Path(tmp)/'review.sqlite3').import_run(raw,'Offline custom test','custom_pipeline')
                self.assertEqual(2,len(run['items']))
