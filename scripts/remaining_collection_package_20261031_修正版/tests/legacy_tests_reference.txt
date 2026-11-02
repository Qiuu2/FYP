"""Offline tests: geography, deduplication, track boundaries, keyword and patent rules."""
import copy
import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import collect as c
import patents


class TestCollection(unittest.TestCase):
    def setUp(self):
        self.w={'id':'W1','title':'Machine-learning methods','publication_year':2024,'type':'article',
                'authorships':[{'author':{'id':'A1','display_name':'Alice'},'institutions':[{'country_code':'HK','display_name':'HK institution'}]},
                               {'author':{'id':'A2','display_name':'Bob'},'institutions':[{'country_code':'US','display_name':'US institution'}]}]}

    def test_local_authors_only(self):
        self.assertEqual(len(c.local_authors(self.w,'HK')),1)
        self.assertEqual(c.local_authors(self.w,'SG'),[])
        row=c.detail(self.w,'HK','X',2024,'conference')
        self.assertEqual(row['author_ids'],'A1')
        self.assertEqual(row['international'],1)
        self.assertEqual(row['top10'],'')

    def test_keywords(self):
        self.assertIn('machine learning',c.keyword_hits(self.w))
        self.assertEqual(c.keyword_hits({'title':'Air and transformers in power stations'}),[])
        self.assertIn('deep learning',c.keyword_hits({'abstract_inverted_index':{'deep':[0],'learning':[1]}}))

    def test_tracks(self):
        for venue,track in [('IJCAI','Demo Track'),('AAAI','IAAI Technical Track'),('NeurIPS','datasets_and_benchmarks_track'),('ACL','findings')]:
            self.assertFalse(c.main_track({'venue':venue,'track':track}))
        self.assertTrue(c.main_track({'venue':'AAAI','track':'AAAI Technical Track on Machine Learning'}))
        self.assertTrue(c.main_track({'venue':'ACL','track':'short'}))

    def test_nonheld(self):
        self.assertEqual(c.catalog_one(None,'ICCV',2024),([], 'not_held'))
        self.assertEqual(c.catalog_one(None,'ECCV',2023),([], 'not_held'))

    def test_openalex_page_limit_and_cursor(self):
        fetch = Mock()
        fetch.get.side_effect = [
            {'results': [{'id': 'W1'}], 'meta': {'next_cursor': 'next', 'count': 1}},
            {'results': [], 'meta': {'next_cursor': None}},
        ]
        self.assertEqual(list(c.oa_pages(fetch, 'publication_year:2024')), [{'id': 'W1'}])
        self.assertEqual([call.args[1]['per_page'] for call in fetch.get.call_args_list], [100, 100])
        self.assertEqual([call.args[1]['cursor'] for call in fetch.get.call_args_list], ['*', 'next'])

    def test_api_error_retains_reason_without_key(self):
        with tempfile.TemporaryDirectory(dir=c.ROOT) as td, patch.object(c, 'CACHE', Path(td)), \
                patch.dict(c.os.environ, {'OPENALEX_API_KEY': 'test-secret'}):
            fetch = c.Fetch()
            response = Mock(status_code=400, text='bad request')
            response.json.return_value = {'message': 'per_page must be <= 100; test-secret'}
            fetch.session.get = Mock(return_value=response)
            with self.assertRaises(RuntimeError) as error:
                fetch.get('https://api.openalex.org/works', as_json=True)
            self.assertIn('per_page must be <= 100', str(error.exception))
            self.assertNotIn('test-secret', str(error.exception))

    def test_completed_year_exported_after_network_failure(self):
        def interrupted_pull(*args, **kwargs):
            c.save_json(c.OUT/'journal_sources.json', [{'source_id':'S1', 'name':'TPAMI', 'keyword_filter':False}])
            work = copy.deepcopy(self.w)
            work['primary_location'] = {'source': {'id':'https://openalex.org/S1'}}
            c.save_json(c.OUT/'oa'/'journals_2024.json', [work])
            raise RuntimeError('network stopped during 2025')

        with tempfile.TemporaryDirectory(dir=c.ROOT) as td, patch.object(c, 'OUT', Path(td)), \
                patch.object(c, 'pull_oa', side_effect=interrupted_pull), \
                patch.object(c.sys, 'argv', ['collect.py', 'journals', '--start', '2024', '--end', '2025']):
            with self.assertRaisesRegex(RuntimeError, 'network stopped'):
                c.main()
            import csv
            with (c.OUT/'papers_HK_SG.csv').open(encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([(r['work_id'], r['year']) for r in rows], [('W1', '2024')])

    def test_patent_window_and_family(self):
        q=patents.sql(2015,2025)
        self.assertIn('20150101 AND 20251231',q)
        self.assertIn('GROUP BY country,family_key',q)
        self.assertIn('publication_fallback',q)
        self.assertEqual(q.count('STARTS_WITH(c.code'),5)

    def test_match_deduplicates_versions_not_countries(self):
        old=c.OUT
        try:
            with tempfile.TemporaryDirectory(dir=c.ROOT) as td:
                assert Path(td).resolve().parent == c.ROOT.resolve()
                c.OUT=Path(td)
                pre=copy.deepcopy(self.w);pre['id']='W2';pre['type']='preprint'
                for y in (2023,2024,2025):
                    c.save_json(c.OUT/'oa'/f'regional_pool_{y}.json',[self.w,pre] if y==2024 else [])
                c.save_json(c.OUT/'catalogs'/'ICML_2024.json',{'venue':'ICML','year':2024,'status':'parsed_unverified','rows':[c.record('ICML',2024,'Machine learning methods','https://example.org/paper')]})
                c.build(2024,2024)
                import csv
                with (c.OUT/'papers_HK_SG.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['work_id'],'W1')
                self.assertEqual(rows[0]['country'],'HK')
        finally:c.OUT=old


if __name__=='__main__':unittest.main()
