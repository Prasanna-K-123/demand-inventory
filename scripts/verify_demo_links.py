"""Check static-hosting links and basic document structure; not browser QA."""
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = []
        self.controls = []
        self.label_depth = 0
        self.labels_for = set()
        self.h1 = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'h1':
            self.h1 += 1
        if tag == 'label':
            self.label_depth += 1
            if 'for' in attrs:
                self.labels_for.add(attrs['for'])
        if tag in ('input', 'select', 'textarea'):
            self.controls.append((attrs.get('id'), self.label_depth > 0,
                                  bool(attrs.get('aria-label') or attrs.get('aria-labelledby'))))
        if tag in ('a', 'img', 'script', 'link'):
            for name in ('href', 'src'):
                if name in attrs:
                    self.links.append(attrs[name])

    def handle_endtag(self, tag):
        if tag == 'label':
            self.label_depth -= 1


def run():
    hosting = (ROOT / 'docs').resolve()
    files = [hosting / 'index.html', *sorted((hosting / 'exports').glob('*.html'))]
    local_count = 0
    control_count = 0
    for path in files:
        content = path.read_text()
        document = Document()
        document.feed(content)
        assert document.h1 == 1, f'Expected one page heading: {path}'
        assert len(document.ids) == len(set(document.ids)), f'Duplicate id: {path}'
        assert '__DATA__' not in content and '__STYLE__' not in content
        for control_id, wrapped, aria_named in document.controls:
            assert wrapped or aria_named or control_id in document.labels_for, f'Unnamed form control: {path}:{control_id}'
            control_count += 1
        for link in document.links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            destination = (path.parent / unquote(parsed.path)).resolve()
            assert destination.is_relative_to(hosting), f'Link escapes hosting root: {path}:{link}'
            assert destination.is_file(), f'Missing target: {path}:{link}'
            if parsed.fragment and destination.suffix == '.html':
                target = Document()
                target.feed(destination.read_text())
                assert unquote(parsed.fragment) in target.ids, f'Missing fragment: {path}:{link}'
            local_count += 1
    output = {
        'passed': True,
        'html_pages': len(files),
        'local_links': local_count,
        'form_controls_with_static_accessible_names': control_count,
        'html_hashes': {p.relative_to(hosting).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        'scope': 'Static local-file resolution, headings, duplicate ids and form labels. Not browser rendering, keyboard, mobile, screen-reader or live-site verification.',
        'browser_verified': False,
        'public_release_complete': False,
    }
    (ROOT / 'reports/demo_link_verification.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({k: v for k, v in output.items() if k != 'html_hashes'}))


if __name__ == '__main__':
    run()
