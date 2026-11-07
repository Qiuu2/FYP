"""Summarize coverage and unresolved review items without network access."""
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def rows(path):
    if not path.exists():
        return []
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def main():
    paper_out = ROOT / 'results' / 'papers'
    expected = [(v, y) for v in ['NeurIPS', 'ICML', 'ICLR', 'CVPR', 'ICCV', 'ECCV', 'ACL', 'EMNLP', 'AAAI', 'IJCAI'] for y in range(2015, 2026)]
    observed = {(r.get('venue', ''), int(r['year'])): r for r in rows(paper_out / 'catalog_status.csv') if r.get('year', '').isdigit()}
    missing = [(v, y) for v, y in expected if (v, y) not in observed]
    status_counts = Counter(r.get('status', 'unknown') for r in observed.values())
    unresolved_states = {'failed', 'needs_retry_or_import', 'parsed_unverified', 'count_review_required', 'track_review_required'}
    unresolved_catalogs = [dict(venue=v, year=y, status=observed[v, y].get('status', '')) for v, y in expected
                           if (v, y) in observed and observed[v, y].get('status', '') in unresolved_states]
    oa = paper_out / 'oa'
    journal_years = sorted(int(p.stem.split('_')[-1]) for p in oa.glob('journals_*.json') if p.stem.split('_')[-1].isdigit())
    pool_years = sorted(int(p.stem.split('_')[-1]) for p in oa.glob('regional_pool_*.json') if p.stem.split('_')[-1].isdigit())
    papers = {
        'expected_catalog_tasks': len(expected),
        'catalog_tasks_found': len(observed),
        'missing_catalog_tasks': [f'{v} {y}' for v, y in missing],
        'catalog_status_counts': dict(status_counts),
        'catalogs_needing_retry_or_review': unresolved_catalogs,
        'openalex_journal_years_found': journal_years,
        'openalex_regional_pool_years_found': pool_years,
        'paper_affiliation_review_rows': len(rows(paper_out / 'review_queue.csv')),
        'paper_track_review_rows': len(rows(paper_out / 'paper_tracks_to_review.csv')),
    }

    patent_manifest_path = ROOT / 'results' / 'patents' / 'manifest.json'
    patent_manifest = json.loads(patent_manifest_path.read_text(encoding='utf-8')) if patent_manifest_path.exists() else None
    annual = rows(ROOT / 'results' / 'patents' / '年度专利.csv')
    pending_assignees = rows(ROOT / 'results' / 'patents' / 'new_assignees_to_classify.csv')
    bio_2025 = [r for r in annual if r.get('industry') == 'biomed' and r.get('year') == '2025']
    patents = {
        'export_found': bool(patent_manifest),
        'export_verified': patent_manifest.get('export_verified', False) if patent_manifest else False,
        'queried_window': patent_manifest.get('filing_window', '') if patent_manifest else '',
        'invalid_rows': patent_manifest.get('invalid_rows', '') if patent_manifest else '',
        'pending_applicant_occurrences': patent_manifest.get('classification_pending', '') if patent_manifest else '',
        'unclassified_assignee_names': len(pending_assignees),
        'biomed_2025_rows': bio_2025,
        'recent_years_remain_provisional': True,
    }

    summary = {
        'scope': 'HK/SG AI and biomed only; finance patents excluded',
        'papers': papers,
        'patents': patents,
        'automatic_complete': False,
        'note': 'Directory retrieval, publisher coverage, author affiliation, and company classification have different review states; inspect the listed CSVs before analysis.',
    }
    out = ROOT / 'results' / 'collection_summary.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
