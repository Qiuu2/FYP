"""Public bibliographic collection. Python 3.10+. Run --help. No credentials in outputs."""
import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
OUT = ROOT / 'results'
CACHE = ROOT / 'cache'


def norm(s):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', s or '').casefold())


def write_csv(path, rows, fields=None):
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields or (list(rows[0]) if rows else ['status']), extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


class Fetch:
    def __init__(self, max_requests=10000):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'HKSG-AI-Academic-Research/1.0'
        self.count = 0
        self.max_requests = max_requests

    def get(self, url, params=None, as_json=False):
        params = dict(params or {})
        public_id = json.dumps([url, params], sort_keys=True)
        file = CACHE / (hashlib.sha256(public_id.encode()).hexdigest() + '.json')
        if file.exists():
            obj = json.loads(file.read_text(encoding='utf-8'))
            return json.loads(obj['body']) if as_json else obj['body']
        if self.count >= self.max_requests:
            raise RuntimeError('REQUEST_LIMIT: restart the same command to resume')
        headers = {}
        if urlparse(url).hostname == 'api.openalex.org' and os.getenv('OPENALEX_API_KEY'):
            headers['Authorization'] = 'Bearer ' + os.environ['OPENALEX_API_KEY']
        for attempt in range(4):
            self.count += 1
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=60)
            except requests.RequestException:
                if attempt == 3:
                    raise RuntimeError('Network error at ' + urlparse(url).netloc) from None
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 429:
                raise RuntimeError('HTTP 429: quota/rate limit; resume later')
            if r.status_code >= 500 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            if r.status_code != 200:
                hint = ''
                if urlparse(url).hostname == 'api.openalex.org':
                    try:
                        body = r.json()
                        hint = str(body.get('message') or body.get('error') or body.get('code') or '')[:600]
                    except (ValueError, AttributeError):
                        pass
                    key = os.getenv('OPENALEX_API_KEY')
                    if key:
                        hint = hint.replace(key, '[REDACTED]')
                    if r.status_code in (401, 403):
                        hint += ' Check your API key and verified email at https://openalex.org/settings/api'
                raise RuntimeError(f'HTTP {r.status_code} at {url}' + (': ' + hint if hint else ''))
            if any(x in r.text[:5000].lower() for x in ['making sure you', 'challengerequirederror']):
                raise RuntimeError('Site challenge; manual access needed: ' + url)
            if as_json:
                try:
                    json.loads(r.text)
                except ValueError:
                    raise RuntimeError('Expected JSON, received HTML: ' + url) from None
            save_json(file, {'url': url, 'params': params, 'retrieved_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'body': r.text})
            time.sleep(0.35)
            return r.json() if as_json else r.text

    def soup(self, url):
        return BeautifulSoup(self.get(url), 'html.parser')


def record(venue, year, title, url, track='main', authors=''):
    return dict(venue=venue, year=year, title=title.strip(), url=url, track=track, authors=authors)


def catalog_one(fetch, venue, year):
    """Official directory entries only; no OpenAlex venue-ID approximation."""
    rows = []
    if (venue == 'ICCV' and year % 2 == 0) or (venue == 'ECCV' and year % 2 == 1):
        return [], 'not_held'
    if venue in ('NeurIPS', 'ICLR') and (venue == 'NeurIPS' or year >= 2024):
        host = 'proceedings.neurips.cc' if venue == 'NeurIPS' else 'proceedings.iclr.cc'
        url = f'https://{host}/paper_files/paper/{year}'
        soup = fetch.soup(url)
        for a in soup.select('a[href]'):
            href = a['href']
            if re.search(rf'/(?:paper|paper_files/paper)/{year}/hash/', href):
                li = a.find_parent('li')
                track = 'main'
                if li:
                    track = li.get('data-track', 'main')
                rows.append(record(venue, year, a.get_text(' ', strip=True), urljoin(url, href), track))
    elif venue == 'ICLR':
        # Older accepted notes have venueid; unaccepted submissions are never included.
        api = 'https://api.openreview.net/notes'
        offset = 0
        while True:
            d = fetch.get(api, {'content.venueid': f'ICLR.cc/{year}/Conference', 'limit': 1000, 'offset': offset}, True)
            notes = d.get('notes', [])
            for n in notes:
                c = n.get('content', {})
                title = c.get('title', '')
                if isinstance(title, dict):
                    title = title.get('value', '')
                rows.append(record(venue, year, title, 'https://openreview.net/forum?id=' + n['id']))
            if len(notes) < 1000:
                break
            offset += len(notes)
    elif venue == 'ICML':
        root = 'https://proceedings.mlr.press/'
        home = fetch.soup(root)
        volumes = []
        for li in home.select('li'):
            text = li.get_text(' ', strip=True)
            if re.search(r'\bICML\b|International Conference on Machine Learning', text) and str(year) in text:
                a = li.find('a', href=True)
                if a:
                    volumes.append(urljoin(root, a['href']).rstrip('/') + '/')
        for url in dict.fromkeys(volumes):
            soup = fetch.soup(url)
            for div in soup.select('div.paper'):
                title = div.select_one('.title')
                a = next((a for a in div.select('a[href]') if a.get_text(strip=True).lower() == 'abs'), None)
                if title and a:
                    rows.append(record(venue, year, title.get_text(' ', strip=True), urljoin(url, a['href'])))
    elif venue in ('CVPR', 'ICCV'):
        url = f'https://openaccess.thecvf.com/{venue}{year}?day=all'
        soup = fetch.soup(url)
        for a in soup.select('dt.ptitle a[href]'):
            href = a['href']
            if 'workshop' not in href.lower():
                rows.append(record(venue, year, a.get_text(' ', strip=True), urljoin(url, href)))
    elif venue == 'ECCV':
        url = 'https://www.ecva.net/papers.php'
        soup = fetch.soup(url)
        for a in soup.select('a[href]'):
            h = a['href']
            if f'eccv_{year}/' in h.lower() and '/html/' in h and 'workshop' not in h.lower():
                rows.append(record(venue, year, a.get_text(' ', strip=True), urljoin(url, h)))
    elif venue in ('ACL', 'EMNLP'):
        url = f'https://aclanthology.org/events/{venue.lower()}-{year}/'
        soup = fetch.soup(url)
        volumes = []
        for a in soup.select('a[href^="#"]'):
            text = a.get_text(' ', strip=True)
            lower = text.lower()
            if 'proceedings' not in lower or any(x in lower for x in ['findings', 'workshop', 'demonstration', 'tutorial', 'student research', 'industry']):
                continue
            if (venue == 'ACL' and 'annual meeting' in lower) or (venue == 'EMNLP' and 'empirical methods' in lower):
                section = soup.find(id=a['href'][1:])
                if section:
                    volumes.append((text, section))
        # The event page has a separate div per volume, with an h4/h3 title.
        for text, section in volumes:
            container = section
            if section.name not in ('div', 'section'):
                container = section.find_parent('div')
            for a in container.select('strong a[href]'):
                href = a['href']
                if re.search(r'(?:\.\d+|[A-Z]\d{2}-\d{4})/$', href) and not re.search(r'(?:\.0|[A-Z]\d{2}-\d000)/$', href):
                    rows.append(record(venue, year, a.get_text(' ', strip=True), urljoin(url, href), 'short' if 'short' in text.lower() else 'main'))
    elif venue == 'IJCAI':
        url = f'https://www.ijcai.org/proceedings/{year}/' if year >= 2017 else ('https://www.ijcai.org/Proceedings/15/' if year == 2015 else 'https://www.ijcai.org/Proceedings/2016/')
        soup = fetch.soup(url)
        for div in soup.select('.paper_wrapper'):
            title = div.select_one('.title')
            a = next((a for a in div.select('a[href]') if re.search(rf'/proceedings/{year}/\d+$', a['href'])), None)
            heading = div.find_previous(['h2', 'h3', 'h4'])
            track = heading.get_text(' ', strip=True) if heading else 'unknown'
            if title and a:
                rows.append(record(venue, year, title.get_text(' ', strip=True), urljoin(url, a['href']), track))
        if year <= 2016:
            for a in soup.select('a[href]'):
                if not re.search(r'/Abstract/\d{2}/\d+$', a['href']):
                    continue
                p = a.find_parent('p')
                if not p:
                    continue
                title = re.sub(r'\s*/\s*\d+\s*$', '', p.get_text('\n', strip=True).split('\n')[0])
                heading = p.find_previous(['h2','h3','h4'])
                track = heading.get_text(' ', strip=True) if heading else 'unknown'
                if re.match(r'^Main Track\b', track):
                    track = 'Main Track'
                else:
                    track = 'unclassified_legacy: ' + track
                rows.append(record(venue, year, title, urljoin(url,a['href']),track))
    elif venue == 'AAAI':
        root = 'https://ojs.aaai.org/index.php/AAAI/'
        issues = {}
        for page in range(1, 12):
            url = root + 'issue/archive' + (f'/{page}' if page > 1 else '')
            soup = fetch.soup(url)
            found = soup.select('.obj_issue_summary')
            if not found:
                break
            for item in found:
                a = item.select_one('a.title')
                text = item.get_text(' ', strip=True)
                if a and re.search(rf'\b{year}\b', text):
                    issues[urljoin(url, a['href'])] = text
            next_link = soup.select_one('a.next')
            if not next_link:
                break
        for url, issue_title in issues.items():
            soup = fetch.soup(url)
            for item in soup.select('.obj_article_summary'):
                a = item.select_one('.title a')
                section = item.find_parent(class_='section')
                heading = section.find(['h2', 'h3']) if section else None
                track = heading.get_text(' ', strip=True) if heading else issue_title
                if a:
                    rows.append(record(venue, year, a.get_text(' ', strip=True), urljoin(url, a['href']), track))
    unique = {r['url']: r for r in rows if r['title']}
    if not unique:
        raise RuntimeError('No entries parsed; requires manual directory/import (not zero papers)')
    return list(unique.values()), 'parsed_unverified'


def main_track(r):
    t = r['track'].lower()
    if r['venue'] == 'IJCAI':
        return t == 'main track'
    if r['venue'] == 'AAAI':
        # Positive inclusion avoids accidentally counting IAAI/EAAI or abstract tracks.
        return ('technical track' in t or 'aaai technical' in t or 'main track' in t) and not any(x in t for x in ['iaai', 'eaai', 'student', 'abstract', 'demo', 'workshop'])
    return not any(x in t for x in ['workshop', 'dataset', 'benchmark', 'demo', 'tutorial', 'findings'])


def collect_catalog(fetch, years, venues):
    directory = OUT / 'catalogs'
    statuses = {}
    status_file = OUT / 'catalog_status.csv'
    if status_file.exists():
        with status_file.open(encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                statuses[(r['venue'], int(r['year']))] = r
    for venue in venues:
        for year in years:
            path = directory / f'{venue}_{year}.json'
            if path.exists():
                obj = json.loads(path.read_text(encoding='utf-8'))
            else:
                try:
                    rows, status = catalog_one(fetch, venue, year)
                    obj = {'venue': venue, 'year': year, 'status': status, 'rows': rows}
                    save_json(path, obj)
                except Exception as e:
                    obj = {'venue': venue, 'year': year, 'status': 'needs_retry_or_import', 'error': str(e), 'rows': []}
            status = {k: v for k, v in obj.items() if k != 'rows'} | {'catalog_rows': len(obj['rows']), 'main_rows': sum(main_track(r) for r in obj['rows'])}
            statuses[(venue, year)] = status
            print(venue, year, status['status'], status['catalog_rows'], flush=True)
            write_csv(status_file, [statuses[k] for k in sorted(statuses)], ['venue', 'year', 'status', 'catalog_rows', 'main_rows', 'error'])


SELECT = 'id,doi,title,publication_year,publication_date,type,authorships,primary_location,abstract_inverted_index,cited_by_count,citation_normalized_percentile,primary_topic'


def oa_pages(fetch, flt, pool=False):
    cursor = '*'
    page, downloaded = 0, 0
    while cursor:
        fields = SELECT.replace(',abstract_inverted_index', '').replace(',primary_topic', '') if pool else SELECT
        d = fetch.get('https://api.openalex.org/works', {'filter': flt, 'select': fields, 'per_page': 100, 'cursor': cursor}, True)
        page += 1
        downloaded += len(d.get('results', []))
        if page == 1 or page % 10 == 0:
            print(f'  page {page}: {downloaded} / {d.get("meta", {}).get("count", "?")} records (cached for resume)', flush=True)
        yield from d.get('results', [])
        new = d.get('meta', {}).get('next_cursor')
        if new == cursor:
            raise RuntimeError('Repeated cursor')
        cursor = new
        if not d.get('results'):
            break


def pull_oa(fetch, years, pool=False, all_ai=False):
    if not os.getenv('OPENALEX_API_KEY'):
        raise RuntimeError('Set OPENALEX_API_KEY first: https://openalex.org/settings/api')
    resolved = []
    if not pool and not all_ai:
        for j in CFG['journals']:
            print('Resolving journal:', j['name'], flush=True)
            source = fetch.get('https://api.openalex.org/sources/issn:' + j['issn'], as_json=True)
            resolved.append(j | {'source_id': source['id'].split('/')[-1], 'resolved_name': source['display_name']})
        save_json(OUT / 'journal_sources.json', resolved)
    label = 'regional_pool' if pool else 'all_ai' if all_ai else 'journals'
    for year in years:
        target = OUT / 'oa' / f'{label}_{year}.json'
        if target.exists():
            print('cached', target.name, flush=True)
            continue
        flt = f'authorships.institutions.country_code:HK|SG,publication_year:{year}'
        if all_ai:
            flt += ',primary_topic.subfield.id:1702'
        elif not pool:
            flt += ',primary_location.source.id:' + '|'.join(j['source_id'] for j in resolved)
        print('Fetching', label, year, '(network requests may take up to 60s each)', flush=True)
        works = list(oa_pages(fetch, flt, pool=pool))
        save_json(target, works)
        print(label, year, len(works), flush=True)


def abstract(w):
    idx = w.get('abstract_inverted_index') or {}
    return ' '.join(t for _, t in sorted((pos, word) for word, positions in idx.items() for pos in positions))


def keyword_hits(w):
    text = unicodedata.normalize('NFKC', (w.get('title') or '') + ' ' + abstract(w)).casefold()
    text = re.sub(r'[-\u2010-\u2015]', ' ', text)
    return [k for k in CFG['keywords'] if re.search(r'(?<!\w)' + re.escape(k).replace(r'\ ', r'\s+') + r'(?!\w)', text)]


def local_authors(w, cc):
    return [a for a in w.get('authorships', []) if any(i.get('country_code') == cc for i in a.get('institutions', []))]


def detail(w, cc, venue, year, kind, hits='', url=''):
    authors = local_authors(w, cc)
    cnp = w.get('citation_normalized_percentile') or {}
    countries = {i['country_code'] for a in w.get('authorships', []) for i in a.get('institutions', []) if i.get('country_code')}
    institutions = {i.get('display_name', '') for a in authors for i in a.get('institutions', []) if i.get('country_code') == cc}
    return dict(year=year, country=cc, category=kind, venue=venue, work_id=w['id'], doi=w.get('doi') or '', title=w.get('title') or '', date=w.get('publication_date'), source_url=url,
                author_ids='|'.join(sorted({a['author']['id'] for a in authors if a.get('author', {}).get('id')})), institutions='|'.join(sorted(institutions)),
                citations=w.get('cited_by_count'), top10=cnp.get('is_in_top_10_percent', ''), top1=cnp.get('is_in_top_1_percent', ''),
                international=int(len(countries) > 1), keyword_hits=hits)


def build(start, end):
    OUT.mkdir(exist_ok=True)
    db = sqlite3.connect(OUT / 'match_index.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS works (id TEXT PRIMARY KEY, title TEXT, year INTEGER, body TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS title_year ON works(title,year)')
    db.execute('CREATE TABLE IF NOT EXISTS loaded (path TEXT PRIMARY KEY, digest TEXT)')
    # Index on disk; do not hold all years of the regional pool in memory.
    for pattern in ('regional_pool_*.json', 'all_ai_*.json', 'journals_*.json'):
        for f in sorted((OUT / 'oa').glob(pattern)):
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            previous = db.execute('SELECT digest FROM loaded WHERE path=?', (f.name,)).fetchone()
            if previous and previous[0] == digest:
                continue
            batch = json.loads(f.read_text(encoding='utf-8'))
            db.executemany('INSERT OR REPLACE INTO works VALUES (?,?,?,?)',
                           ((w['id'],norm(w.get('title')),w.get('publication_year',0),json.dumps(w,ensure_ascii=False)) for w in batch))
            db.execute('INSERT OR REPLACE INTO loaded VALUES (?,?)', (f.name,digest))
            db.commit()
            del batch
    journal_file = OUT / 'journal_sources.json'
    journals = {j['source_id']: j for j in json.loads(journal_file.read_text(encoding='utf-8'))} if journal_file.exists() else {}
    details, review, coverage = [], [], []
    journal_works = {}
    for file in sorted((OUT / 'oa').glob('journals_*.json')):
        for w in json.loads(file.read_text(encoding='utf-8')):
            journal_works[w['id']] = w
    for w in journal_works.values():
        year = w.get('publication_year', 0)
        if not start <= year <= end:
            continue
        source = ((w.get('primary_location') or {}).get('source') or {}).get('id', '').split('/')[-1]
        j = journals.get(source)
        if j and w.get('type') in ('article', 'review'):
            hits = keyword_hits(w)
            if not j['keyword_filter'] or hits:
                for cc in CFG['countries']:
                    if local_authors(w, cc):
                        details.append(detail(w, cc, j['name'], year, 'journal_' + w['type'], '|'.join(hits)))
            elif not w.get('abstract_inverted_index'):
                review.append({'venue': j['name'], 'year': year, 'title': w.get('title'), 'url': w.get('doi'), 'reason': 'no_abstract_and_no_title_keyword'})
    for file in sorted((OUT / 'catalogs').glob('*.json')):
        obj = json.loads(file.read_text(encoding='utf-8'))
        year, venue = obj['year'], obj['venue']
        if not start <= year <= end:
            continue
        rows = list({norm(r['title']): r for r in obj['rows'] if main_track(r)}.values())
        matched = set()
        for r in rows:
            candidates = [json.loads(x[0]) for x in db.execute('SELECT body FROM works WHERE title=? AND year BETWEEN ? AND ?', (norm(r['title']),year-1,year+1))]
            # Multiple records may be preprint/proceedings versions. Merge by catalog paper;
            # ambiguous author identities are queued, not auto-merged.
            if len(candidates) > 1:
                firsts = {norm((w.get('authorships') or [{}])[0].get('author', {}).get('display_name', '')) for w in candidates}
                if len(firsts) != 1 or '' in firsts:
                    review.append({'venue': venue, 'year': year, 'title': r['title'], 'url': r['url'], 'reason': 'ambiguous_title_match'})
                    continue
            if not candidates:
                review.append({'venue': venue, 'year': year, 'title': r['title'], 'url': r['url'], 'reason': 'not_in_HK_SG_OpenAlex_pool; may_be_foreign_or_missing_affiliation'})
                continue
            for cc in CFG['countries']:
                local = [w for w in candidates if local_authors(w, cc)]
                if local:
                    w = max(local, key=lambda x: (x.get('type') != 'preprint', len(local_authors(x, cc))))
                    row = detail(w, cc, venue, year, 'conference', url=r['url'])
                    details.append(row)
                    matched.add((cc, norm(r['title'])))
        pool_ready = all((OUT / 'oa' / f'regional_pool_{y}.json').exists() for y in range(year-1, year+2))
        for cc in CFG['countries']:
            n = sum(c == cc for c, _ in matched)
            coverage.append({'venue': venue, 'year': year, 'country': cc, 'catalog_main_papers': len(rows),
                             'identified_local_papers': n if pool_ready else '', 'regional_pool_complete': int(pool_ready),
                             'directory_status': obj['status'], 'identified_share_of_catalog': n/len(rows) if rows and pool_ready else ''})
    unique = {(r['category'], r['venue'], r['year'], r['country'], r['source_url'] or r['work_id']): r for r in details}
    details = list(unique.values())
    write_csv(OUT / 'papers_HK_SG.csv', details)
    write_csv(OUT / 'review_queue.csv', review, ['venue', 'year', 'title', 'url', 'reason'])
    write_csv(OUT / 'conference_coverage.csv', coverage)
    groups = defaultdict(list)
    for r in details:
        groups[(r['year'], r['country'], r['category'], r['venue'])].append(r)
    annual = []
    for (year, cc, cat, venue), items in sorted(groups.items()):
        ids = {a for r in items for a in r['author_ids'].split('|') if a}
        known = [r for r in items if r['top10'] != '']
        annual.append({'year': year, 'country': cc, 'category': cat, 'venue': venue, 'papers': len(items), 'local_author_ids': len(ids),
                       'international_share': sum(r['international'] for r in items)/len(items),
                       'top10_share_among_known': sum(r['top10'] for r in known)/len(known) if known else '', 'top10_known_papers': len(known)})
    write_csv(OUT / 'annual_summary.csv', annual)
    # Broad 1702 sample remains separate from selected journal/conference counts.
    ai = []
    for file in sorted((OUT / 'oa').glob('all_ai_*.json')):
        for w in json.loads(file.read_text(encoding='utf-8')):
            for cc in CFG['countries']:
                if local_authors(w, cc):
                    ai.append(detail(w, cc, 'OpenAlex_AI_1702', w['publication_year'], 'all_ai'))
    if ai:
        write_csv(OUT / 'all_ai_HK_SG.csv', ai)
    db.close()
    print('Built results:', OUT, flush=True)


def import_catalog(path):
    groups = defaultdict(list)
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            r['year'] = int(r['year'])
            groups[(r['venue'], r['year'])].append(r)
    for (venue, year), rows in groups.items():
        if venue not in CFG['conferences']:
            raise ValueError('Unknown venue: ' + venue)
        save_json(OUT / 'catalogs' / f'{venue}_{year}.json', {'venue': venue, 'year': year, 'status': 'manual_import_unverified', 'rows': rows})


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['catalog', 'journals', 'pool', 'all-ai', 'build', 'all', 'import-catalog'])
    p.add_argument('--start', type=int, default=CFG['start_year'])
    p.add_argument('--end', type=int, default=CFG['end_year'])
    p.add_argument('--venues', nargs='+', choices=CFG['conferences'])
    p.add_argument('--max-requests', type=int, default=10000)
    p.add_argument('--file')
    args = p.parse_args()
    if args.start > args.end:
        p.error('start > end')
    fetch = Fetch(args.max_requests)
    years = list(range(args.start, args.end + 1))
    if args.mode == 'import-catalog':
        if not args.file:
            p.error('--file required')
        import_catalog(args.file)
    else:
        try:
            if args.mode in ('catalog', 'all'):
                collect_catalog(fetch, years, args.venues or CFG['conferences'])
            if args.mode in ('journals', 'all'):
                pull_oa(fetch, years)
            if args.mode in ('pool', 'all'):
                pull_oa(fetch, range(args.start-1, args.end+2), pool=True)
            if args.mode == 'all-ai':
                pull_oa(fetch, years, all_ai=True)
        except (Exception, KeyboardInterrupt):
            print('Collection stopped; exporting completed years. Partial years remain in cache.', flush=True)
            build(args.start, args.end)
            raise
        build(args.start, args.end)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Stopped. Cache retained; rerun the same command to resume.')
        sys.exit(130)
    except Exception as e:
        print('Stopped:', str(e), '\nCache retained; rerun the same command to resume.', file=sys.stderr)
        sys.exit(1)
