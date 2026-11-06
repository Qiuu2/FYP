"""Create a reproducible side-by-side audit from existing data; does not mutate sources."""
import argparse,csv,json
from pathlib import Path
def read(path):
    with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(path,fields,rows):
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def main():
    p=argparse.ArgumentParser();p.add_argument('--result',required=True);p.add_argument('--baseline',required=True);p.add_argument('--ai2025',required=True);p.add_argument('--supplement',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    prior=json.loads(Path(a.result).read_text(encoding='utf-8'))
    base={(r['industry'],r['city'],r['family_id']):r for r in read(a.baseline)}
    for r in read(a.ai2025):
        k=(r['industry'],r['city'],r['family_id'])
        if k in base:raise ValueError('Historical snapshot and 2025 overlap: '+str(k))
        base[k]=r
    sup={(r['industry'],r['family_id']):r for r in read(a.supplement)}
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True); rows=[]
    for c in prior['year_mismatch']:
        industry,city,fam=c['key'];b=base[(industry,city,fam)];s=sup[(industry,fam)]
        rows.append(dict(industry=industry,city=city,family_id=fam,local_filing=b['first_filing_in_window'],
            supplemental_window_filing=s['first_filing'],local_year=c['base_year'],supplement_year=c['supp_year'],
            interpretation='different source filters; preserve both dates; not necessarily an error'))
    write(out/'historical_77_date_scope_differences.csv',list(rows[0]),rows)
    cand=prior['unknown_university_names'];write(out/'university_names_pending.csv',list(cand[0]),cand)
    summary=dict(source_hashes=prior['input_sha256'],count_conflicts=len(rows),count_suspected_university=len(cand),
        treatment='different date definitions; original local filing remains the displayed year; manual review still required')
    (out/'audit_manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('日期口径差异:',len(rows),'疑似大学名称:',len(cand))
if __name__=='__main__':main()
