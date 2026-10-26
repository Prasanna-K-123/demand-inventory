"""Reproducibility inventory and narrow static security checks, not a CVE audit."""
import ast,importlib.metadata as md,json,re,subprocess,sys
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from stockout.common import atomic_json,file_hash
BASE=Path(__file__).resolve().parents[1]
names=[line.split("==")[0] for line in (BASE/"requirements.txt").read_text().splitlines() if line]
seen={};todo=names[:]
while todo:
    name=todo.pop();key=canonicalize_name(name)
    if key in seen:continue
    dist=md.distribution(name);seen[key]={"version":dist.version,"license_expression":dist.metadata.get("License-Expression"),"metadata_license":(dist.metadata.get("License") or "")[:100]}
    for r in dist.requires or []:
        dep=Requirement(r)
        if dep.marker is None or dep.marker.evaluate({"extra":""}):todo.append(dep.name)
(BASE/"requirements.lock").write_text("# Exact installed dependency closure for direct project requirements; Python 3.12 on Windows\n"+"".join(f"{n}=={v['version']}\n" for n,v in sorted(seen.items())))
check=subprocess.run([sys.executable,"-m","pip","check"],capture_output=True,text=True,timeout=30)
syntax=[];shell_calls=[];secret_hits=[]
for f in list((BASE/"src").rglob("*.py"))+list((BASE/"scripts").glob("*.py"))+list((BASE/"tests").glob("*.py")):
    text=f.read_text();tree=ast.parse(text);syntax.append(str(f.relative_to(BASE)))
    for node in ast.walk(tree):
        if isinstance(node,ast.Call):
            for kw in node.keywords:
                if kw.arg=="shell" and isinstance(kw.value,ast.Constant) and kw.value.value is True:shell_calls.append(str(f.relative_to(BASE)))
    # Only high-specificity key forms; hashes/model identifiers are expected public evidence.
    if re.search(r"sk-"+r"(?:proj-)?[A-Za-z0-9_-]{35,}",text):secret_hits.append(str(f.relative_to(BASE)))
report={"python":sys.version.split()[0],"direct_requirements_sha256":file_hash(BASE/"requirements.txt"),"lock_sha256":file_hash(BASE/"requirements.lock"),"dependency_count":len(seen),"dependencies":seen,"pip_check_exit":check.returncode,"pip_check_output":check.stdout.strip()+check.stderr.strip(),"python_files_parsed":len(syntax),"shell_true_calls":shell_calls,"high_specificity_secret_pattern_hits":secret_hits,"known_vulnerability_audit":"not performed; no claim that installed packages are vulnerability-free","security_boundaries":["bind IPv4 loopback only; no authentication/TLS, therefore never expose directly","1 MiB request-body cap and typed item limits","SQL values parameterized; static table names only","only bundled trusted pickle accepted, SHA256 checked before deserialization; digest is corruption detection, not publisher authentication","source digests and immutable conflict quarantine","raw source data and SQLite runtime excluded from repository"]}
atomic_json(BASE/"artifacts/dependency_security_receipt.json",report)
assert not shell_calls and not secret_hits
print(json.dumps({k:v for k,v in report.items() if k!="dependencies"},indent=2))
