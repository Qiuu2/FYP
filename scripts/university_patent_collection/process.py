"""Summarise publication-level BigQuery export. Python >=3.9, standard library only."""
import argparse, csv, hashlib, json, re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
YEARS = range(2015, 2026)
PREFIX = {'ai': ('G06N','G06V','G10L','G06F40','B25J'), 'biomed': ('A61','C12','C07K','C07D','G16H')}
UNIV_LIKE = re.compile(r'UNIV|UNIVERSIT|UNIVERST|POLYTECH|HKUST|CUHK|HKBU|NANYANG|\bNUS\b',re.I)
def read(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def write(p,fields,rows):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def date(value,field,required=False):
    value=str(value or '').strip()
    if value in ('','0','None','null'):
        if required:raise ValueError('Missing '+field)
        return ''
    if not re.fullmatch(r'\d{8}',value):raise ValueError('Invalid '+field+': '+value)
    try: datetime.strptime(value,'%Y%m%d')
    except ValueError: raise ValueError('Invalid '+field+': '+value)
    return value
def norm(v):return str(v or '').strip().upper()
def load_config():
    sectors={}; aliases={}
    for name in ('institution_sectors.csv','private_sectors.csv'):
        path=ROOT/'config'/name
        if not path.exists():continue
        for r in read(path):
            key=norm(r['assignee']); val=r['sector'].strip()
            if key in sectors and sectors[key]!=val:raise ValueError('Conflicting sector mapping '+key)
            sectors[key]=val
    for r in read(ROOT/'config'/'university_aliases.csv'):
        key=norm(r['assignee']); val=(r['city'].lower(),r['univ'],r['tier'])
        if key in aliases and aliases[key]!=val:raise ValueError('Conflicting university alias '+key)
        aliases[key]=val
    for r in read(ROOT/'config'/'reviewed_aliases.csv'):
        status=r['status'].strip();key=norm(r['assignee'])
        if status=='pending':
            aliases.pop(key,None);sectors.pop(key,None)
        elif status=='confirmed':
            key=norm(r['assignee']);city=r['city'].strip().lower();tier=r['tier'].strip()
            if city not in ('hk','sg') or tier not in ('A','B'):raise ValueError('Bad reviewed alias '+key)
            val=(city,r['univ'].strip(),tier)
            if key in aliases and aliases[key]!=val:raise ValueError('Review conflicts with existing alias '+key)
            aliases[key]=val;sectors[key]='university'
        else:raise ValueError('Alias review status must be pending or confirmed: '+key)
    return sectors,aliases
def parse_export(src):
    rows=read(src); metadata=[r for r in rows if r.get('row_type')=='manifest']; data=[r for r in rows if r.get('row_type')=='data']
    if len(metadata)!=1 or len(rows)!=len(data)+1:raise ValueError('Need ALL export rows including exactly one manifest sentinel')
    if not data:raise ValueError('Empty export cannot establish absence of patents; check query and CSV')
    try: expected=int(metadata[0]['total_rows'])
    except (KeyError,ValueError):raise ValueError('Invalid manifest row count')
    if expected!=len(data) or any(int(r['total_rows'])!=expected for r in data):raise ValueError('Truncated/inconsistent CSV export')
    seen=set();families=defaultdict(list)
    for r in data:
        fam=r['family_id'].strip();pub=r['publication_number'].strip()
        if fam in ('','0','-1','None','null') or not pub:raise ValueError('Missing family or publication identifier')
        if pub in seen:raise ValueError('Duplicate publication '+pub)
        seen.add(pub)
        r['filing_date']=date(r['filing_date'],'filing_date',True)
        r['publication_date']=date(r.get('publication_date'),'publication_date')
        r['priority_date']=date(r.get('priority_date'),'priority_date')
        if not 2015<=int(r['filing_date'][:4])<=2025:raise ValueError('Filing outside 2015-2025')
        try:
            r['applicants']=json.loads(r['applicants_json']);r['cpc']=json.loads(r['cpc_json']);r['inventors']=json.loads(r['inventor_countries_json'])
        except (ValueError,KeyError,TypeError) as e:raise ValueError('Invalid JSON for '+pub) from e
        if not isinstance(r['applicants'],list) or not isinstance(r['cpc'],list) or not isinstance(r['inventors'],list):raise ValueError('Expected JSON lists')
        if any(not isinstance(a,dict) or not a.get('name') for a in r['applicants']):raise ValueError('Missing applicant name: '+pub)
        families[fam].append(r)
    return families,metadata[0]
def run(src,out):
    families,meta=parse_export(src);sectors,aliases=load_config(); audit=[];pending=[];conflicts=[]
    counts=defaultdict(set); uncertain=defaultdict(set)
    applicant_records={}
    for fam,pubs in families.items():
        for p in pubs:
            for a in p['applicants']:
                name=norm(a.get('name'));cc=norm(a.get('country_code'));alias=aliases.get(name)
                key=(fam,name,cc)
                if key not in applicant_records:
                    applicant_records[key]=dict(family_id=fam,assignee=name,country_code=cc,
                        sector=sectors.get(name,'university_alias' if alias and alias[2] in ('A','B') else 'unclassified'),
                        university=alias[1] if alias else '',university_city=alias[0] if alias else '',
                        university_tier=alias[2] if alias else '',first_seen_filing=p['filing_date'],
                        publication_numbers=set())
                applicant_records[key]['first_seen_filing']=min(applicant_records[key]['first_seen_filing'],p['filing_date'])
                applicant_records[key]['publication_numbers'].add(p['publication_number'])
    for fam,pubs in families.items():
        for industry,prefixes in PREFIX.items():
            hits=[r for r in pubs if any(str(code).startswith(prefixes) for code in r['cpc'])]
            if not hits:continue
            for city in ('hk','sg'):
                local=[];global_names=set();local_names=set();unknown=set(); unknown_dates=[]
                for p in pubs:
                    for a in p['applicants']:
                        name=norm(a.get('name')); cc=norm(a.get('country_code')).lower(); alias=aliases.get(name)
                        if alias and alias[0]==city and alias[2]=='A': global_names.add(name)
                        isuni=sectors.get(name)=='university' or (alias and alias[0]==city and alias[2]=='A')
                        if p in hits and cc==city and isuni:
                            local.append(p['filing_date']);local_names.add(name)
                        hint=(cc==city or (city=='hk' and ('HONG KONG' in name or 'HKUST' in name or 'CUHK' in name)) or
                              (city=='sg' and ('SINGAPORE' in name or 'NANYANG' in name)))
                        if UNIV_LIKE.search(name) and hint and name not in sectors and not alias:
                            unknown.add(name);unknown_dates.append(p['filing_date'])
                gdate=min(p['filing_date'] for p in pubs)
                ldate=min(local) if local else ''
                priority=min((p['priority_date'] for p in pubs if p['priority_date']),default='')
                expanded=bool(local_names or global_names)
                if ldate:
                    counts[(industry,city,int(ldate[:4]),'local')].add(fam)
                # Reproduce the documented existing hybrid: local year if present, otherwise first family filing in window.
                if expanded:
                    chosen=ldate or gdate
                    counts[(industry,city,int(chosen[:4]),'expanded')].add(fam)
                    audit.append(dict(industry=industry,city=city,family_id=fam,local_filing=ldate,
                        family_window_filing=gdate,priority_date_observed=priority,expanded_year=chosen[:4],
                        local_university_names=' | '.join(sorted(local_names)),global_body_names=' | '.join(sorted(global_names)),
                        publication_numbers=' | '.join(sorted(p['publication_number'] for p in pubs)),
                        classification_note='existing alias map; institutional affiliation and geography need review'))
                    if ldate and ldate[:4]!=gdate[:4]: conflicts.append(dict(industry=industry,city=city,family_id=fam,
                        local_filing=ldate,family_window_filing=gdate,priority_date_observed=priority,
                        chosen_year=ldate[:4],reason='different filing scope; no overwrite of original dates'))
                if unknown:
                    # Unknowns may overlap confirmed universities; report flags, not extra counts.
                    for name in sorted(unknown): pending.append(dict(industry=industry,city=city,family_id=fam,name=name,
                        earliest_observed_date=min(unknown_dates),also_has_known_university=bool(expanded),status='pending_manual_review'))
                    if not expanded:
                        y=int(min(unknown_dates)[:4]);uncertain[(industry,city,y,'local')].add(fam);uncertain[(industry,city,y,'expanded')].add(fam)
    annual=[]
    for y in YEARS:
      for industry in PREFIX:
       for city in ('hk','sg'):
        for scope in ('local','expanded'):
            key=(industry,city,y,scope);known=len(counts[key]);unc=len(uncertain[key])
            annual.append(dict(year=y,industry=industry,city=city,scope=scope,known_families=known,
                potential_unknown_families=unc,usable_observed_count=known if not unc else '',
                status=('pending_classification' if unc else 'observed_only')+(';recent_incomplete' if y>=2024 else ''),
                note='Published, name-map limited; not total unpublished applications; candidate matching not exhaustive'))
    out.mkdir(parents=True,exist_ok=True)
    write(out/'年度大学专利.csv',list(annual[0]),annual)
    write(out/'大学专利族明细.csv',['industry','city','family_id','local_filing','family_window_filing','priority_date_observed','expanded_year','local_university_names','global_body_names','publication_numbers','classification_note'],audit)
    applicants=[]
    for r in applicant_records.values():
        r['publication_numbers']=' | '.join(sorted(r['publication_numbers']));applicants.append(r)
    write(out/'申请人分类明细.csv',['family_id','assignee','country_code','sector','university','university_city','university_tier','first_seen_filing','publication_numbers'],applicants)
    write(out/'申请人待核查.csv',['industry','city','family_id','name','earliest_observed_date','also_has_known_university','status'],pending)
    write(out/'年份差异.csv',['industry','city','family_id','local_filing','family_window_filing','priority_date_observed','chosen_year','reason'],conflicts)
    manifest={'created_utc':datetime.now(timezone.utc).isoformat(),'source_sha256':hashlib.sha256(Path(src).read_bytes()).hexdigest(),
              'sql_sha256':hashlib.sha256((ROOT/'sql'/'university_patents_2015_2025.sql').read_bytes()).hexdigest(),
              'input_publications':int(meta['total_rows']),'query_utc':meta['query_utc'],'max_publication_date':meta['max_publication_date'],
              'config_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'config').glob('*.csv'))},
              'family_count':len(families),'year_conflicts':len(conflicts),'pending_rows':len(pending),'completed':False,
              'note':'Observed records only, incomplete classification and publication; no forecast; original publication dates retained.'}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('完成：',out,'已核查族记录',len(audit),'待核行',len(pending),'年份差异',len(conflicts))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--csv',type=Path,required=True,help='full BigQuery CSV including manifest')
    p.add_argument('--out',type=Path,default=ROOT/'results');args=p.parse_args();run(args.csv,args.out)
if __name__=='__main__':main()
