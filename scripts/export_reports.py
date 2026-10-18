"""Prepare own reports/artifacts under the static hosting root."""
import html,re,shutil
from pathlib import Path
from urllib.parse import unquote,urlsplit
from report_html import render
ROOT=Path(__file__).resolve().parents[1]

def export_reports():
    target=ROOT/'docs/exports';target.mkdir(parents=True,exist_ok=True)
    style=(ROOT/'docs/style.css').read_text()+"\narticle{background:white;padding:25px;border:1px solid #d8e2e7;border-radius:10px}article h1{font-size:29px}article h2{margin-top:28px}article table{display:block;overflow-x:auto}article pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf3f6;padding:14px}article img{max-width:100%;height:auto}article p,article li{overflow-wrap:anywhere}"
    pages={
      'reports/TECHNICAL_REPORT.md':'technical_report.html',
      'reports/RESEARCH_PAPER.md':'research_paper.html',
      'reports/DECISION_MEMO.md':'decision_memo.html',
      'reports/FORECAST_BRIEF.md':'forecast_brief.html',
      'PROTOCOL.md':'protocol.html',
      'HEDGE_PROTOCOL.md':'hedge_protocol.html',
      'docs/SOURCES.md':'sources.html'
    }
    available={(ROOT/source).resolve():name for source,name in pages.items() if (ROOT/source).exists()}
    def rewrite(body,source):
        def link(match):
            attribute,url=match[1],html.unescape(match[2])
            parsed=urlsplit(url)
            if parsed.scheme or parsed.netloc or not parsed.path:return match[0]
            local=(source.parent/unquote(parsed.path)).resolve()
            if local in available:
                destination=available[local]
            elif local.is_relative_to(ROOT/'reports') and local.suffix in ('.json','.svg','.png') and local.is_file():
                destination=local.name
                shutil.copyfile(local,target/destination)
            else:
                raise ValueError('Unsupported local report link: '+str(source)+': '+url)
            if parsed.fragment:destination+='#'+parsed.fragment
            return attribute+'="'+html.escape(destination,quote=True)+'"'
        return re.sub(r'(href|src)="([^"]*)"',link,body)
    for source,name in pages.items():
        path=ROOT/source
        if not path.exists():continue
        body=rewrite(render(path.read_text()),path)
        title=next((line.lstrip('# ').strip() for line in path.read_text().splitlines() if line.startswith('# ')), 'Research report')
        document='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>'+style+'</style></head><body><main><p><a href="../index.html">Back to the explorer</a></p><article>'+body+'</article></main></body></html>'
        (target/name).write_text(document)
    for directory,patterns in [('reports',['*.svg','*.png']),('output/pdf',['*.pdf']),('outputs',['*.xlsx'])]:
        for pattern in patterns:
            for source in (ROOT/directory).glob(pattern):shutil.copyfile(source,target/source.name)
    return target
