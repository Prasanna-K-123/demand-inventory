# Exact public-file boundaries; no fitted objects, private audits, raw source or row-level predictions.
import argparse,hashlib,json,shutil
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
TOP=['README.md','LICENSE','DATA_LICENSE.md','pyproject.toml','requirements.txt','requirements.lock','.gitignore','protocol.json','protocol.sha256','protocol-addendum.json','protocol-addendum.sha256']
ARTIFACTS=['source_audit.json','cohort.csv','cohort_receipt.json','attrition.json','forecast_metrics.csv','interval_metrics.json','bootstrap.json','weekly_metrics.csv','weekly_summary.json','artificial_masking.json','decision_days.csv','decision_summary.json','forecast_mae.png','error_over_time.png','ledger_ingestion_receipt.json','model_manifest.json','research_receipt.json','recovery_receipt.json','benchmark.json','http_smoke.json','demo_result.json','dependency_security_receipt.json','observed_failures.json','tests.xml','public_tests.xml','tests-final-fencing.xml','integration_summary.json','service_eligibility_difference.json','static_checks.json','review_status.json','explorer_calculation_smoke.json']
def files():
    result=TOP+[str(f.relative_to(BASE)).replace('\\','/') for pattern in ['src/stockout/*.py','scripts/*.py','tests/*.py','docs/*.md','docs/*.json','.github/workflows/*.yml'] for f in BASE.glob(pattern)]
    result += ['fixtures/real_history.json','explorer/index.html','explorer/template.html']
    result += ['artifacts/'+n for n in ARTIFACTS]
    return sorted(set(result))
def main(dest):
    paths=files();missing=[n for n in paths if not (BASE/n).is_file()]
    if missing:raise FileNotFoundError(str(missing))
    manifest={'schema':1,'root':'.','files':[{'path':n,'sha256':hashlib.sha256((BASE/n).read_bytes()).hexdigest(),'bytes':(BASE/n).stat().st_size} for n in paths],'excluded':['models.pkl','row-level forecast CSV/GZIP exports','artifacts/audit/','raw source parquet','runtime SQLite/logs','private defense and verification'],'expected_public_test_scope':'38 artifact-free tests; 6 local-fitted-artifact tests explicitly skipped unless regenerated','pages_source':'explorer/','repository':'Prasanna-K-123/demand-inventory'}
    (BASE/'public_allowlist.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    if dest:
        dest=dest.resolve();dest.mkdir(parents=True,exist_ok=True)
        for n in paths:
            target=dest/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(BASE/n,target)
        shutil.copyfile(BASE/'public_allowlist.json',dest/'public_allowlist.json')
    print(json.dumps({'public_files':len(paths),'bytes':sum(f['bytes'] for f in manifest['files']),'staging':str(dest) if dest else None}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path);main(p.parse_args().stage)
