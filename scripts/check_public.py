# Static and content QA only: this does not claim visual browser testing.
import ast,hashlib,json,re
from html.parser import HTMLParser
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
class Inspect(HTMLParser):
    def __init__(self):super().__init__();self.ids=[];self.labels=[];self.links=[];self.scripts=[];self.script=None;self.selects=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.append(a['id'])
        if tag=='label':self.labels.append(a.get('for'))
        if tag=='select':self.selects.append(a.get('id'))
        if tag=='a':self.links.append(a.get('href',''))
        if tag=='script':self.script={'type':a.get('type','text/javascript'),'id':a.get('id'),'source':''}
    def handle_data(self,text):
        if self.script is not None:self.script['source']+=text
    def handle_endtag(self,tag):
        if tag=='script' and self.script is not None:self.scripts.append(self.script);self.script=None
html=(BASE/'explorer/index.html').read_text(encoding='utf-8-sig');p=Inspect();p.feed(html)
assert len(p.ids)==len(set(p.ids)) and all(s in p.labels for s in p.selects)
assert all(link[1:] in p.ids for link in p.links if link.startswith('#'))
assert '__DATA__' not in html and '<meta name="viewport"' in html
payload=json.loads(next(s['source'] for s in p.scripts if s['id']=='evidence-data'))
assert 'traces' not in payload
summary=json.loads((BASE/'artifacts/integration_summary.json').read_text())
assert payload['summary']==summary
assert payload['benchmark']['completed_jobs']==200 and not payload['benchmark']['errors']
assert summary['systems']['test_failures']==0 and summary['systems']['allocation_parity']
assert sum(r['n'] for r in payload['metrics'] if r['split']=='final' and r['model']=='pooled_poisson')==55128
missing=[]
for f in [BASE/'README.md',*list((BASE/'docs').glob('*.md'))]:
    for link in re.findall(r'\]\(([^)]+)\)',f.read_text(encoding='utf-8-sig')):
        if '://' in link or link.startswith('#'):continue
        if not (f.parent/link.split('#')[0]).exists():missing.append({'file':str(f.relative_to(BASE)),'link':link})
assert not missing,missing
pyfiles=list((BASE/'src').rglob('*.py'))+list((BASE/'scripts').glob('*.py'))+list((BASE/'tests').glob('*.py'))
for f in pyfiles:ast.parse(f.read_text(encoding='utf-8-sig'))
for name in ['protocol','protocol-addendum']:
    assert hashlib.sha256((BASE/(name+'.json')).read_bytes()).hexdigest()==(BASE/(name+'.sha256')).read_text().split()[0]
report={'html_static_checks':'passed','python_files_parsed':len(pyfiles),'unique_element_ids':len(p.ids),'labelled_selects':len(p.selects),'local_markdown_links':'passed','inline_saved_results_match_summary':True,'public_trace_export_absent':True,'protocol_hashes_match':True,'no_browser_qa':True,'scope':'HTML structure, labels, anchors, local links, embedded data concordance and Python syntax; no browser layout or accessibility conformance certification'}
(BASE/'artifacts/static_checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
