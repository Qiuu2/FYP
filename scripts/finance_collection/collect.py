#!/usr/bin/env python3
"""Collect OpenAlex finance works and aggregate exported BigQuery patent families."""
import argparse, csv, datetime, json, os, pathlib, sys, time, urllib.parse, urllib.request, urllib.error
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / 'results'
OUT.mkdir(exist_ok=True)

def write_csv(path, headers, rows):
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=headers); w.writeheader(); w.writerows(rows)
    temp.replace(path)

def get_json(params, key):
    params['api_key'] = key
    url = 'https://api.openalex.org/works?' + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'FYP-finance-research/1.0'}), timeout=90) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, 'code', None)
            if code in (401, 403): raise RuntimeError(f'OpenAlex HTTP {code}: 检查API key、账户权限和额度') from None
            if code is not None and code not in (429, 500, 502, 503, 504): raise RuntimeError(f'OpenAlex HTTP {code}; 检查查询参数') from None
            if attempt == 4: raise RuntimeError('OpenAlex请求失败或限流，请重试；原有成功结果保留') from None
            time.sleep(2 ** attempt)

def extract_authors(work, country):
    result = set(); missing = 0
    for item in work.get('authorships', []):
        if any(i.get('country_code') == country for i in item.get('institutions', [])):
            aid = (item.get('author') or {}).get('id')
            if aid: result.add(aid.rsplit('/',1)[-1])
            else: missing += 1
    return result, missing

def fetch_cell(year, country, scope, key):
    topic_filter = ('primary_topic' if scope == 'primary' else 'topics') + '.subfield.id:2003'
    filters = f'publication_year:{year},authorships.institutions.country_code:{country},{topic_filter},type:article'
    cursor='*'; seen=set(); authors=set(); missing=0; reported=None; pages=0
    while cursor:
        doc=get_json({'filter':filters,'per-page':200,'cursor':cursor,'select':'id,authorships'},key)
        if reported is None: reported=doc['meta']['count']
        pages+=1
        for work in doc.get('results',[]):
            wid=work.get('id')
            if not wid or wid in seen: continue
            seen.add(wid); ids,n=extract_authors(work,country); authors.update(ids); missing+=n
        cursor=doc['meta'].get('next_cursor')
    if len(seen) != reported: raise RuntimeError(f'{year} {country}: 去重后{len(seen)}篇，但服务端报告{reported}篇；不写入该年度结果')
    return {'year':year,'country':country,'scope':scope,'works':len(seen),'authors':sorted(authors),'missing_author_ids':missing,'pages':pages,'server_count':reported,'filter':filters}

def papers(args):
    key=os.environ.get('OPENALEX_API_KEY','').strip()
    if not key: raise RuntimeError('请先设置 OPENALEX_API_KEY 环境变量，密钥不要写入文件或发到群里')
    saved=OUT/'papers_cells'; saved.mkdir(exist_ok=True)
    failed=[]
    # Two preceding years are required for a valid three-year author window.
    for country in args.countries.split(','):
        country=country.upper().strip()
        if country not in ('HK','SG'): raise ValueError('地区只支持 HK,SG')
        for year in range(args.start-2,args.end+1):
            path=saved/f'{args.scope}_{country}_{year}.json'
            if path.exists() and not args.refresh: continue
            try:
                obj=fetch_cell(year,country,args.scope,key)
                tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8');tmp.replace(path)
                print(f'{country} {year}: 论文 {obj["works"]}, 作者 {len(obj["authors"])}',flush=True)
            except Exception as e:
                failed.append({'country':country,'year':year,'error':str(e)})
                print(f'{country} {year} 失败: {e}',file=sys.stderr,flush=True)
                break
    rows=[]
    for country in args.countries.split(','):
        country=country.upper().strip()
        for year in range(args.start,args.end+1):
            cells=[]
            for yy in (year-2,year-1,year):
                path=saved/f'{args.scope}_{country}_{yy}.json'
                failed_cell=any(x['country']==country and x['year']==yy for x in failed)
                cells.append(json.loads(path.read_text(encoding='utf-8')) if path.exists() and not failed_cell else None)
            current=cells[-1]
            ids=set().union(*(set(c['authors']) for c in cells if c))
            rows.append({'region':country,'year':year,'scope':args.scope,'finance_articles':current['works'] if current else '',
              'active_authors_3yr':len(ids) if all(cells) else '', 'missing_author_ids':sum(c['missing_author_ids'] for c in cells if c) if all(cells) else '',
              'status':'ok' if all(cells) else 'incomplete', 'source':'OpenAlex; article; finance subfield 2003'})
    write_csv(OUT/'finance_papers_annual.csv',list(rows[0]),rows)
    (OUT/'papers_manifest.json').write_text(json.dumps({'collected_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'start':args.start,'end':args.end,'countries':args.countries,'scope':args.scope,'failures':failed,'note':'current OpenAlex snapshot; not a real-time historical vintage'},ensure_ascii=False,indent=2),encoding='utf-8')
    if failed: raise RuntimeError('部分年度未完成，结果已标记 incomplete；修正后重跑以续采')

def patents(args):
    with open(args.csv,encoding='utf-8-sig',newline='') as f: data=list(csv.DictReader(f))
    required={'family_id','city','first_filing_in_window','assignees','cpc_codes'}
    if not data or not required.issubset(data[0]): raise ValueError('CSV为空或缺少SQL输出字段')
    with open(args.classification,encoding='utf-8-sig',newline='') as f:
        rules={r['assignee'].strip().casefold():r['sector'].strip().lower() for r in csv.DictReader(f)}
    allowed={'financial_firm','other_company','university','public_rd','individual','other','unknown'}
    if any(v not in allowed for v in rules.values()): raise ValueError('申请人分类存在不支持的类型')
    groups=defaultdict(lambda: {'all':set(),'financial_firm':set(),'unknown':set()});review=defaultdict(int); seen=set()
    for r in data:
        family=r['family_id'].strip();city=r['city'].upper().strip()
        if not family or city not in ('HK','SG'): raise ValueError('缺少有效family_id或地区')
        year=int(r['first_filing_in_window'][:4]); pair=(city,family)
        if pair in seen: raise ValueError(f'同一地区专利族重复: {pair}')
        seen.add(pair); g=groups[(city,year)];g['all'].add(family)
        names=[x.strip() for x in r['assignees'].split(' | ') if x.strip()]
        if not names: raise ValueError(f'缺少申请人: {pair}')
        for name in names:
            sector=rules.get(name.casefold(),'unknown')
            if sector=='financial_firm':g['financial_firm'].add(family)
            if sector=='unknown':g['unknown'].add(family);review[name]+=1
    rows=[{'region':c,'year':y,'all_finance_cpc_families':len(g['all']),'confirmed_financial_firm_families':len(g['financial_firm']),
           'families_with_unknown_assignee':len(g['unknown']),'status':'published_observation_classification_incomplete' if g['unknown'] else 'published_observation',
           'note':'not all finance industry innovation; group counts overlap'} for (c,y),g in sorted(groups.items())]
    write_csv(OUT/'finance_patents_annual.csv',list(rows[0]),rows)
    write_csv(OUT/'assignees_to_review.csv',['assignee','sector','family_appearances'],[{'assignee':n,'sector':'unknown','family_appearances':v} for n,v in sorted(review.items())])
    (OUT/'patents_manifest.json').write_text(json.dumps({'collected_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'input':str(args.csv),'rows':len(data),'notes':'All families are observed published records. Year is earliest HK/SG qualifying filing inside query window.'},ensure_ascii=False,indent=2),encoding='utf-8')
    print('已生成专利年度汇总和待分类申请人清单；不存在的年份不能自动视为零。')

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('papers'); a.add_argument('--start',type=int,default=2015); a.add_argument('--end',type=int,default=2025);a.add_argument('--countries',default='HK,SG');a.add_argument('--scope',choices=['primary','any'],default='primary');a.add_argument('--refresh',action='store_true')
    b=sub.add_parser('patents');b.add_argument('--csv',required=True);b.add_argument('--classification',default=str(ROOT/'assignees.csv'))
    args=p.parse_args()
    if args.cmd=='papers' and (args.start<1902 or args.end<args.start): p.error('年份范围不正确')
    try: papers(args) if args.cmd=='papers' else patents(args)
    except Exception as e: print('错误:',str(e),file=sys.stderr);return 1
    return 0
if __name__=='__main__': sys.exit(main())
