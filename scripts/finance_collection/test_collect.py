import csv, pathlib, tempfile, unittest
from unittest.mock import patch
import collect

class Tests(unittest.TestCase):
    def test_author_geo_and_dedup(self):
        work={'authorships':[{'author':{'id':'https://openalex.org/A1'},'institutions':[{'country_code':'HK'}]},
                             {'author':{'id':'https://openalex.org/A1'},'institutions':[{'country_code':'HK'}]},
                             {'author':{},'institutions':[{'country_code':'HK'}]},
                             {'author':{'id':'A2'},'institutions':[{'country_code':'SG'}]}]}
        self.assertEqual(collect.extract_authors(work,'HK'),({'A1'},1))

    def test_pagination_dedup_and_incomplete(self):
        responses=[{'meta':{'count':1,'next_cursor':'x'},'results':[{'id':'W1','authorships':[]}]},
                   {'meta':{'count':1,'next_cursor':None},'results':[{'id':'W1','authorships':[]}]}]
        with patch.object(collect,'get_json',side_effect=responses):
            self.assertEqual(collect.fetch_cell(2020,'HK','primary','secret')['works'],1)
        with patch.object(collect,'get_json',return_value={'meta':{'count':2,'next_cursor':None},'results':[]}):
            with self.assertRaises(RuntimeError): collect.fetch_cell(2020,'HK','primary','secret')

    def test_patent_groups_unknown_and_no_zero(self):
        with tempfile.TemporaryDirectory(dir=collect.ROOT) as d:
            d=pathlib.Path(d); src=d/'x.csv'; rules=d/'rules.csv'; out=d/'out';out.mkdir()
            src.write_text('family_id,city,first_filing_in_window,assignees,cpc_codes\n1,HK,20200101,BANK | MYSTERY,G06Q40\n2,HK,20210101,MYSTERY,G06Q40\n',encoding='utf-8')
            rules.write_text('assignee,sector\nBANK,financial_firm\n',encoding='utf-8')
            with patch.object(collect,'OUT',out): collect.patents(type('Args',(),{'csv':str(src),'classification':str(rules)})())
            with (out/'finance_patents_annual.csv').open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
            self.assertEqual(rows[0]['confirmed_financial_firm_families'],'1');self.assertEqual(rows[0]['families_with_unknown_assignee'],'1')
            self.assertEqual(rows[1]['status'],'published_observation_classification_incomplete')
            self.assertEqual(len(rows),2)
if __name__=='__main__':unittest.main()
