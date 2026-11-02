"""Repair catalogs, reuse OpenAlex caches, and merge into preserved baseline results."""
import argparse,collections,csv,json,os,re,shutil,sys
from pathlib import Path
from urllib.parse import urljoin,urlparse
import paper_base as base
from common import ROOT,read_csv,write_csv,save_json,digest,now

OUT=ROOT/'results/papers';BASELINE=ROOT/'baseline/papers'
base.OUT=OUT;base.CACHE=ROOT/'cache/http'
ORIGINAL_CATALOG=base.catalog_one
FAILED=[('AAAI',y) for y in range(2015,2026)]+[('ICLR',y) for y in range(2015,2024)]+[('CVPR',y) for y in range(2018,2021)]+[('ECCV',2016),('ICCV',2019),('IJCAI',2016),('NeurIPS',2025)]
FLOORS={'NeurIPS':1000,'CVPR':500,'ICCV':400,'ECCV':300,'ICML':200,'ICLR':30,'AAAI':300,'ACL':100,'EMNLP':100,'IJCAI':300}

def main_track(r):
    t=r.get('track','').casefold().strip()
    if not t or any(x in t for x in ['unknown','unclassified','workshop','dataset','benchmark','demo','tutorial','findings','creative','position','student','abstract','doctoral','iaai','eaai','sister','what’s hot',"what's hot",'nectar']):return False
    if r['venue']=='AAAI':return t in ('main','technical track') or 'technical track' in t or 'aaai technical' in t or 'main track' in t
    if r['venue']=='IJCAI':return t in ('main','main track')
    return True
base.main_track=main_track

def unique(rows):return list({base.norm(r['title']):r for r in rows if base.norm(r.get('title'))}.values())

def neurips(fetch,year):
    url=f'https://proceedings.neurips.cc/paper_files/paper/{year}'
    soup=fetch.soup(url)
    # 2025's bare year URL is Creative AI. Follow the linked Main Conference volume.
    links=[urljoin(url,a['href']) for a in soup.select('a[href]') if 'main conference' in a.get_text(' ',strip=True).casefold()]
    if links:
        url=links[0];soup=fetch.soup(url)
    h=soup.find('h1');heading=h.get_text(' ',strip=True) if h else ''
    if 'creative' in heading.casefold():raise RuntimeError('Creative AI is not the main research proceedings')
    rows=[]
    for a in soup.select('a[href]'):
        if not re.search(rf'/(?:paper|paper_files/paper)/{year}/hash/',a['href']):continue
        li=a.find_parent('li');track=li.get('data-track','main') if li else 'main'
        badge=li.select_one('.paper-track-badge') if li else None
        if badge:track=badge.get_text(' ',strip=True)
        row=base.record('NeurIPS',year,a.get_text(' ',strip=True),urljoin(url,a['href']),track)
        authors=li.select_one('.paper-authors') if li else None
        if authors:row['authors']=authors.get_text(' ',strip=True)
        rows.append(row)
    rows=unique(rows)
    declared=re.search(r'([\d,]+)\s+papers',soup.get_text(' ',strip=True),re.I)
    expected=int(declared[1].replace(',','')) if declared else None
    if expected is not None and expected!=len(rows):raise RuntimeError(f'NeurIPS directory truncated: {len(rows)} / {expected}')
    return rows,dict(source_url=url,expected_count=expected,verification='publisher_count_matched' if expected else 'parsed_count_unverified')

def cvf(fetch,venue,year):
    root=f'https://openaccess.thecvf.com/{venue}{year}'
    soup=fetch.soup(root);pages=[(root,soup)]
    if not soup.select('dt.ptitle a[href]'):
        # Older editions link real daily pages; ?day=all can legitimately return an empty page.
        days=list(dict.fromkeys(urljoin(root,a['href']) for a in soup.select('a[href]') if re.search(r'day=\d{4}-\d{2}-\d{2}',a['href']) and f'{venue}{year}' in a['href']))
        if not days:days=[root+'?day=all']
        pages=[(u,fetch.soup(u)) for u in days]
    rows=[]
    for url,soup in pages:
        page=[]
        for a in soup.select('dt.ptitle a[href]'):
            if 'workshop' in a['href'].lower():continue
            page.append(base.record(venue,year,a.get_text(' ',strip=True),urljoin(url,a['href'])))
        if not page:raise RuntimeError('A scheduled daily page parsed no papers: '+url)
        rows+=page
    return unique(rows),dict(source_url=root,pages=[p[0] for p in pages],verification='all_linked_days_parsed')

def ijcai(fetch,year):
    if year==2016:
        url='https://ijcai-16.org/index.php/welcome/view/accepted_papers/'
        soup=fetch.soup(url);rows=[]
        for panel in soup.select('.panel'):
            heading=panel.select_one('.panel-heading')
            if not heading or heading.get_text(' ',strip=True)!='Main Track':continue
            for li in panel.select('.panel-body li'):
                b=li.find('b')
                if not b:continue
                title=re.sub(r'^\(\d+\)\s*','',b.get_text(' ',strip=True))
                rows.append(base.record('IJCAI',year,title,url+'#main-'+str(len(rows)+1),'Main Track'))
        if not rows:raise RuntimeError('IJCAI 2016 official Main Track list not parsed')
        return unique(rows),dict(source_url=url,verification='official_main_track_acceptance_list')
    url=f'https://www.ijcai.org/Proceedings/{year}/' if year<=2016 else f'https://www.ijcai.org/proceedings/{year}/'
    soup=fetch.soup(url);rows=[]
    for div in soup.select('.paper_wrapper'):
        a=div.select_one('a.title[href]')
        if not a:
            a=next((a for a in div.select('a[href]') if re.search(rf'/proceedings/{year}/\d+$',a['href'])),None)
        title=div.select_one('.title')
        if not a or not title:continue
        text=div.get_text(' ',strip=True);h=div.find_previous(['h2','h3','h4']);track=h.get_text(' ',strip=True) if h else 'unknown'
        # The redesigned 2016 page discards old track headers. Only full-length papers
        # are candidates; do not silently label every 651 record as Main Track.
        if track.casefold()=='papers':
            track='unknown_requires_track_review'
        if re.match(r'^Main Track\b',track,re.I):track='Main Track'
        rows.append(base.record('IJCAI',year,title.get_text(' ',strip=True),urljoin(url,a['href']),track))
    if not rows:rows,_=ORIGINAL_CATALOG(fetch,'IJCAI',year)
    return unique(rows),dict(source_url=url,verification='track_review_required' if any('unknown' in r['track'] or 'unclassified' in r['track'] for r in rows) else 'parsed_count_unverified')

def iclr(fetch,year):
    rows=[]
    if year<=2016:
        url=f'https://iclr.cc/archive/www/{year}.html';soup=fetch.soup(url)
        for h in soup.select('h3'):
            title=h.get_text(' ',strip=True).casefold()
            if title not in ('conference oral presentations','may 9 conference poster session','accepted papers (conference track)'):continue
            section=h.find_next_sibling('div')
            if not section:continue
            for a in section.select('a[href]'):
                if 'arxiv.org/' in a['href']:
                    rows.append(base.record('ICLR',year,a.get_text(' ',strip=True),a['href'].replace('http://','https://')))
    elif year in (2018,2019):
        url=f'https://iclr.cc/Conferences/{year}/Schedule?type=Poster';soup=fetch.soup(url)
        for card in soup.select('.maincard.poster'):
            title=card.select_one('.maincardBody');a=card.select_one('a.href_PDF[href]')
            if title and a:rows.append(base.record('ICLR',year,title.get_text(' ',strip=True),urljoin(url,a['href'])))
    elif 2021<=year<=2023:
        url=f'https://iclr.cc/virtual/{year}/papers.html';soup=fetch.soup(url)
        for a in soup.select('a[href]'):
            if re.fullmatch(rf'/virtual/{year}/(?:poster|oral)/\d+',a['href']):rows.append(base.record('ICLR',year,a.get_text(' ',strip=True),urljoin(url,a['href'])))
    else:
        rows,status=ORIGINAL_CATALOG(fetch,'ICLR',year)
        return rows,dict(verification=status)
    if not rows:raise RuntimeError('ICLR accepted-paper directory yielded no records')
    return unique(rows),dict(source_url=url,verification='official_accepted_directory')

def aaai(fetch,year):
    root='https://ojs.aaai.org/index.php/AAAI/'
    url=root+'issue/archive';seen=set();issues={}
    while url and url not in seen:
        seen.add(url);soup=fetch.soup(url)
        for item in soup.select('.obj_issue_summary'):
            a=item.select_one('a.title[href]');text=item.get_text(' ',strip=True)
            if a and re.search(rf'\({year}\)',text):issues[urljoin(url,a['href'])]=text
        # OJS pagination links vary; no fixed 11-page cutoff.
        a=soup.select_one('a.next[href], a.cmp_pagination__next[href], a[rel="next"][href]')
        if not a:a=next((x for x in soup.select('a[href]') if x.get_text(' ',strip=True).lower() in ('next','next page','older issues','>','»')),None)
        url=urljoin(url,a['href']) if a else None
        if len(seen)>200:raise RuntimeError('AAAI archive pagination exceeds 200 pages; inspect site change')
    if not issues:raise RuntimeError('No AAAI issues discovered for '+str(year))
    rows=[]
    for url,issue_title in issues.items():
        soup=fetch.soup(url);items=soup.select('.obj_article_summary')
        if not items:raise RuntimeError('AAAI issue yielded no articles: '+url)
        for item in items:
            a=item.select_one('.title a[href]');section=item.find_parent(class_='section')
            heading=section.find(['h2','h3']) if section else None
            track=heading.get_text(' ',strip=True) if heading else issue_title
            if a:rows.append(base.record('AAAI',year,a.get_text(' ',strip=True),urljoin(url,a['href']),track))
    return unique(rows),dict(source_url=root+'issue/archive',pages=list(issues),verification='issue_sections_parsed')

def catalog_one(fetch,venue,year):
    if (venue=='ECCV' and year%2) or (venue=='ICCV' and not year%2):return [],dict(verification='not_held')
    if venue=='NeurIPS':return neurips(fetch,year)
    if venue in ('CVPR','ICCV'):return cvf(fetch,venue,year)
    if venue=='IJCAI':return ijcai(fetch,year)
    if venue=='AAAI':return aaai(fetch,year)
    if venue=='ICLR':return iclr(fetch,year)
    rows,status=ORIGINAL_CATALOG(fetch,venue,year)
    return rows,dict(verification=status)

def overrides(venue,year,rows):
    path=ROOT/'config/paper_track_overrides.csv'
    if not path.exists():return rows
    lookup={(r['venue'],int(r['year']),base.norm(r['title'])):r for r in read_csv(path)}
    for r in rows:
        edit=lookup.get((venue,year,base.norm(r['title'])))
        if edit and edit.get('evidence_url') and edit.get('track'):r['track']=edit['track'];r['track_evidence']=edit['evidence_url']
    return rows

def status_catalog(obj):
    rows=obj['rows'];v=obj['venue'];y=int(obj['year']);n=sum(main_track(r) for r in rows)
    if obj.get('verification')=='not_held':state='not_held'
    elif not rows:state='failed'
    elif any('unknown' in r.get('track','') or 'unclassified' in r.get('track','') for r in rows):state='track_review_required'
    elif n<FLOORS[v]:state='count_review_required'
    else:state='parsed_needs_coverage_review'
    if obj.get('verification')=='publisher_count_matched' and state=='parsed_needs_coverage_review':state='publisher_catalog_verified'
    return dict(venue=v,year=y,status=state,catalog_rows=len(rows),main_rows=n,source_url=obj.get('source_url',''),error=obj.get('error',''))

def catalogs(fetch,all_years=False,force=False,only=None):
    jobs=FAILED+([(v,y) for v in base.CFG['conferences'] for y in range(2015,2026) if (v,y) not in FAILED] if all_years else [])
    if only:jobs=only
    status={}
    for f in [BASELINE/'catalog_status.csv',OUT/'catalog_status.csv']:
        if f.exists():status.update({(r['venue'],int(r['year'])):r for r in read_csv(f)})
    for v,y in jobs:
        path=OUT/'catalogs'/f'{v}_{y}.json'
        obj=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if not obj or force or not obj.get('rows'):
            try:
                rows,metadata=catalog_one(fetch,v,y)
                obj=dict(venue=v,year=y,rows=rows,**metadata,retrieved_utc=now(),collector_version=2)
                save_json(path,obj)
            except Exception as e:
                status[v,y]=dict(venue=v,year=y,status='failed',catalog_rows='',main_rows='',error=str(e))
                print('CATALOG',v,y,'FAILED:',e,flush=True)
                write_csv(OUT/'catalog_status.csv',status.values(),['venue','year','status','catalog_rows','main_rows','source_url','error'])
                if '429' in str(e) or 'REQUEST_LIMIT' in str(e):break
                continue
        obj['rows']=overrides(v,y,obj['rows']);status[v,y]=status_catalog(obj)
        obj['status']=status[v,y]['status'];save_json(path,obj)
        print('CATALOG',v,y,obj['status'],len(obj['rows']),flush=True)
        write_csv(OUT/'catalog_status.csv',status.values(),['venue','year','status','catalog_rows','main_rows','source_url','error'])

def strict_pages(fetch,flt,pool=False):
    cursor='*';seen=set();works={};expected=None;page=0
    fields=base.SELECT.replace(',abstract_inverted_index','').replace(',primary_topic','') if pool else base.SELECT
    while cursor:
        if cursor in seen:raise RuntimeError('Repeated OpenAlex cursor; year not committed')
        seen.add(cursor);d=fetch.get('https://api.openalex.org/works',{'filter':flt,'select':fields,'per_page':100,'cursor':cursor},True)
        expected=int(d['meta']['count']) if expected is None else expected;items=d.get('results',[]);page+=1
        for w in items:works[w['id']]=w
        if page==1 or page%10==0:print('OpenAlex',len(works),'/',expected,flush=True)
        cursor=d['meta'].get('next_cursor')
        if not items:break
    if len(works)!=expected:raise RuntimeError(f'OpenAlex incomplete year: {len(works)} / {expected}; keep cache and retry')
    return iter(works.values())
base.oa_pages=strict_pages

def metadata(fetch):
    if not os.getenv('OPENALEX_API_KEY'):raise RuntimeError('OpenAlex key required; use launcher to enter it privately')
    tasks=[('journals',y) for y in range(2015,2026)]+[('regional_pool',y) for y in range(2014,2027)]
    for label,y in tasks:
        try:base.pull_oa(fetch,[y],pool=label=='regional_pool')
        except Exception as e:
            save_json(OUT/'last_metadata_error.json',dict(label=label,year=y,error=str(e),time=now()))
            raise

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    # Legacy matcher handles exact titles / adjacent publication years. It cannot assert
    # that an unmatched global catalog paper is foreign, so unresolved rows stay visible.
    base.build(2015,2025)
    fresh=read_csv(OUT/'papers_HK_SG.csv');old=read_csv(BASELINE/'papers_HK_SG.csv')
    catalogs={}
    for f in (OUT/'catalogs').glob('*.json'):
        o=json.loads(f.read_text(encoding='utf-8'))
        if o['rows']:catalogs[o['venue'],int(o['year'])]=o
    years={int(f.stem.split('_')[-1]) for f in (OUT/'oa').glob('journals_*.json')}
    combined={}
    def key(r):return (r['category'],r['venue'],int(r['year']),r['country'],base.norm(r['title']))
    for r in old:
        v,y=r['venue'],int(r['year'])
        if r['category'].startswith('journal') and y in years:continue
        if r['category']=='conference' and (v,y) in catalogs:
            accepted={base.norm(x['title']):x for x in catalogs[v,y]['rows'] if main_track(x)}
            match=accepted.get(base.norm(r['title']))
            if not match:continue  # removes wrongly included Creative AI etc.
            r['source_url']=match['url']
        r['record_origin']='previous_github_snapshot';combined[key(r)]=r
    for r in fresh:r['record_origin']='refreshed_metadata';combined[key(r)]=r
    rows=list(combined.values())
    fields=list(old[0])+['record_origin'] if old else list(fresh[0])+['record_origin']
    write_csv(OUT/'papers_HK_SG.csv',rows,fields)
    groups=collections.defaultdict(list)
    for r in rows:groups[(r['year'],r['country'],r['category'],r['venue'])].append(r)
    annual=[]
    for (y,c,cat,v),items in sorted(groups.items()):
        ids={x for r in items for x in r['author_ids'].split('|') if x}
        annual.append(dict(year=y,country=c,category=cat,venue=v,identified_papers=len(items),identified_local_authors=len(ids),status='identified_observations_not_exhaustive'))
    write_csv(OUT/'年度论文.csv',annual,['year','country','category','venue','identified_papers','identified_local_authors','status'])
    coverage=[]
    for (v,y),o in sorted(catalogs.items()):
        main={base.norm(x['title']) for x in o['rows'] if main_track(x)}
        ready=all((OUT/'oa'/f'regional_pool_{t}.json').exists() for t in range(y-1,y+2))
        for c in ('HK','SG'):
            n=sum(r['category']=='conference' and r['venue']==v and int(r['year'])==y and r['country']==c for r in rows)
            coverage.append(dict(venue=v,year=y,country=c,catalog_main_papers=len(main),identified_local_papers=n,
                regional_pool_complete=int(ready),directory_status=status_catalog(o)['status']))
    write_csv(OUT/'conference_coverage.csv',coverage,['venue','year','country','catalog_main_papers','identified_local_papers','regional_pool_complete','directory_status'])
    # Preserve old unresolved journal and conference questions outside refreshed scopes.
    review=read_csv(OUT/'review_queue.csv')
    for r in read_csv(BASELINE/'review_queue.csv'):
        if (r['venue'],int(r['year'])) not in catalogs and not (r['venue'] in [j['name'] for j in base.CFG['journals']] and int(r['year']) in years):review.append(r)
    review=list({tuple(r.get(k,'') for k in ['venue','year','title','url','reason']):r for r in review}.values())
    write_csv(OUT/'review_queue.csv',review,['venue','year','title','url','reason'])
    tracks=[dict(venue=v,year=y,title=r['title'],url=r['url'],track=r['track'],evidence_url='') for (v,y),o in catalogs.items() for r in o['rows'] if 'unknown' in r['track'] or 'unclassified' in r['track']]
    write_csv(OUT/'paper_tracks_to_review.csv',tracks,['venue','year','title','url','track','evidence_url'])
    save_json(OUT/'manifest.json',dict(created_utc=now(),papers=len(rows),unresolved_review_rows=len(review),track_review_rows=len(tracks),complete=False,
        baseline_sha256=digest(BASELINE/'papers_HK_SG.csv'),note='Identified HK/SG affiliation observations; no missing-data imputation. Successful parsing is not universal affiliation coverage.'))

def import_existing(path):
    path=Path(path);results=path/'results' if (path/'results').is_dir() else path
    # Data-only whitelist, never copy .env, credentials or arbitrary executables.
    for sub in ['oa','catalogs']:
        for f in (results/sub).glob('*.json'):
            dest=OUT/sub/f.name
            if dest.exists():continue
            obj=json.loads(f.read_text(encoding='utf-8'))
            if sub=='catalogs' and (obj.get('venue'),int(obj.get('year',0))) in FAILED:continue
            if sub=='oa' and not isinstance(obj,list):continue
            save_json(dest,obj)
    if (results/'journal_sources.json').exists():shutil.copy2(results/'journal_sources.json',OUT/'journal_sources.json')
    print('Imported existing data-only caches from',path)

def import_catalog(path):
    grouped=collections.defaultdict(list)
    for r in read_csv(path):
        v=r['venue'];y=int(r['year'])
        if v not in base.CFG['conferences'] or not 2015<=y<=2025:raise ValueError('Invalid venue/year')
        if not r['title'].strip() or not r['url'].startswith('https://'):raise ValueError('Each paper needs a title and source URL')
        if not r.get('track'):r['track']='unknown_requires_track_review'
        r['year']=y;grouped[v,y].append(r)
    for (v,y),rows in grouped.items():
        obj=dict(venue=v,year=y,rows=unique(rows),verification='manual_import_unverified',retrieved_utc=now())
        obj['status']=status_catalog(obj)['status'];save_json(OUT/'catalogs'/f'{v}_{y}.json',obj)
    catalogs(base.Fetch(1),only=list(grouped))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['catalogs','metadata','build','all','import-existing','import-catalog'])
    p.add_argument('--all-catalogs',action='store_true');p.add_argument('--force',action='store_true')
    p.add_argument('--max-requests',type=int,default=2000);p.add_argument('--path',type=Path)
    a=p.parse_args();fetch=base.Fetch(a.max_requests)
    try:
        if a.mode in ('import-existing','import-catalog'):
            if not a.path:p.error('--path is required')
            (import_existing if a.mode=='import-existing' else import_catalog)(a.path)
        if a.mode in ('catalogs','all'):catalogs(fetch,a.all_catalogs,a.force)
        if a.mode in ('metadata','all'):metadata(fetch)
    finally:
        build()
if __name__=='__main__':main()
