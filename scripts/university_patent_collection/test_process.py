import csv,json,tempfile,unittest,shutil
from pathlib import Path
from unittest.mock import patch
import process

FIELDS=['row_type','publication_number','family_id','filing_date','publication_date','priority_date','publication_country','applicants_json','cpc_json','inventor_countries_json','total_rows','max_publication_date','query_utc']
def pub(no,fam,filing,names,cpcs,priority='20191201'):
    return dict(row_type='data',publication_number=no,family_id=fam,filing_date=filing,publication_date='20261101',priority_date=priority,
                publication_country='WO',applicants_json=json.dumps([{'name':n,'country_code':c} for n,c in names]),cpc_json=json.dumps(cpcs),
                inventor_countries_json='[]',total_rows='',max_publication_date='20261101',query_utc='2026-11-07 00:00:00 UTC')
def make(rows,path,manifest=True):
    for r in rows:r['total_rows']=str(len(rows))
    m={k:'' for k in FIELDS};m.update(row_type='manifest',total_rows=str(len(rows)),max_publication_date='20261101',query_utc='2026-11-07 00:00:00 UTC')
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows);w.writerows([m] if manifest else [])
def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
class CollectionTests(unittest.TestCase):
 def test_pending_review_overrides_legacy_alias(self):
    sectors,aliases=process.load_config()
    self.assertNotIn('NAT UNIVERESITY OF SINGAPORE',aliases)
    self.assertNotIn('NAT UNIVERESITY OF SINGAPORE',sectors)
 def test_multiscope_pending_and_overlap(self):
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);src=root/'in.csv';out=root/'out'
        rows=[pub('WO1','F1','20200102',[('NAT UNIV SINGAPORE','SG')],[]),
              pub('WO2','F1','20210102',[('NAT UNIV SINGAPORE','SG'),('COMPANY LTD','SG')],['G06N','A61']),
              pub('WO3','F2','20240303',[('CHINESE UNIV OF HONG KONG','CN')],['C12']),
              pub('WO4','F3','20250104',[('NAT UNIVERSTIY OF SINGAPORE','SG')],['G06N'])]
        make(rows,src);process.run(src,out);a=read(out/'年度大学专利.csv')
        def find(y,industry,city,scope):return next(z for z in a if (z['year'],z['industry'],z['city'],z['scope'])==(str(y),industry,city,scope))
        self.assertEqual(find(2021,'ai','sg','local')['known_families'],'1')
        self.assertEqual(find(2021,'biomed','sg','local')['known_families'],'1')
        self.assertEqual(find(2024,'biomed','hk','expanded')['known_families'],'1')
        self.assertEqual(find(2024,'biomed','hk','local')['known_families'],'0')
        self.assertEqual(find(2025,'ai','sg','local')['potential_unknown_families'],'1')
        self.assertEqual(find(2025,'ai','sg','local')['usable_observed_count'],'')
        conflicts=read(out/'年份差异.csv');self.assertEqual(len(conflicts),2)
        self.assertTrue(all(c['local_filing']=='20210102' and c['family_window_filing']=='20200102' for c in conflicts))
 def test_rejects_truncation_duplicate_and_bad_date(self):
    with tempfile.TemporaryDirectory() as d:
        path=Path(d)/'data.csv';r=pub('WO1','F1','20200102',[('NAT UNIV SINGAPORE','SG')],['G06N'])
        make([r.copy()],path,manifest=False)
        with self.assertRaisesRegex(ValueError,'manifest'):process.parse_export(path)
        make([r.copy(),r.copy()],path)
        with self.assertRaisesRegex(ValueError,'Duplicate publication'):process.parse_export(path)
        r['filing_date']='2020111';make([r],path)
        with self.assertRaisesRegex(ValueError,'Invalid filing_date'):process.parse_export(path)
 def test_confirmed_alias_is_included_only_after_review(self):
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);cfg=root/'config';cfg.mkdir()
        for path in (process.ROOT/'config').glob('*.csv'):shutil.copy(path,cfg/path.name)
        alias=cfg/'reviewed_aliases.csv';rows=read(alias)
        rows[0]['status']='confirmed'
        with alias.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        src=root/'in.csv';make([pub('WO1','F1','20250104',[('NAT UNIVERSTIY OF SINGAPORE','SG')],['G06N'])],src)
        with patch.object(process,'ROOT',root):
            (root/'sql').mkdir();shutil.copy(Path(__file__).parent/'sql'/'university_patents_2015_2025.sql',root/'sql')
            process.run(src,root/'out')
        a=read(root/'out'/'年度大学专利.csv');r=next(r for r in a if (r['year'],r['industry'],r['city'],r['scope'])==('2025','ai','sg','local'))
        self.assertEqual(r['known_families'],'1');self.assertEqual(r['potential_unknown_families'],'0')
if __name__=='__main__':unittest.main()
