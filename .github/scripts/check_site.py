"""Check local navigation, accessibility basics, and a 50 KB page budget."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
PAGE_BUDGET = 50_000  # HTML plus the largest possible image, before compression.


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.tags = []
        self.ids = set()
        self.links = []
        self.images = []
        self.title = ''
        self.in_title = False
        self.feed(path.read_text(encoding='utf-8'))

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        self.tags.append(tag)
        if 'id' in attrs:
            assert attrs['id'] not in self.ids, f'{self.path.name}: duplicate id'
            self.ids.add(attrs['id'])
        if tag == 'a':
            self.links.append(attrs.get('href', ''))
        elif tag == 'img':
            self.images.append(attrs)
        elif tag == 'title':
            self.in_title = True
        assert tag not in ('script', 'iframe', 'link'), f'{self.path.name}: unexpected dependency'
        assert not any(key.startswith('on') for key in attrs), 'Inline scripts are not needed'

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def local_target(page, url):
    parts = urlsplit(url)
    assert not parts.scheme and not parts.netloc and not parts.path.startswith('/'), f'Expected portable local URL: {url}'
    target = (page.parent / unquote(parts.path)).resolve() if parts.path else page
    assert target.is_relative_to(ROOT) and target.is_file(), f'Broken link or asset: {url}'
    return target, unquote(parts.fragment)


pages = {path: Page(path) for path in ROOT.glob('*.html')}
assert len(pages) == 3, 'The assignment requires three pages'
assert len({page.title for page in pages.values()}) == 3, 'Use unique page titles'
assets = set()
for path, page in sorted(pages.items()):
    assert page.title.strip(), f'{path.name}: missing title'
    assert page.tags.count('h1') == 1, f'{path.name}: expected one h1'
    assert all(tag in page.tags for tag in ('header', 'main', 'h2', 'p', 'style', 'img'))
    source = path.read_text(encoding='utf-8')
    assert not re.search(r'@import|url\s*\(', source), 'Unexpected CSS network dependency'
    destinations = set()
    for href in page.links:
        target, fragment = local_target(path, href)
        assert target in pages, f'Link is not a site page: {href}'
        assert not fragment or fragment in pages[target].ids, f'Broken fragment: {href}'
        destinations.add(target)
    assert destinations == pages.keys(), f'{path.name}: each page must be reachable'
    page_bytes = path.stat().st_size
    for img in page.images:
        assert img.get('alt', '').strip(), f'{path.name}: image needs alt text'
        assert all(int(img.get(key, 0)) > 0 for key in ('width', 'height')), 'Reserve image space'
        assert img.get('sizes') and img.get('srcset'), 'Keep images responsive'
        urls = [img['src']] + [item.strip().split()[0] for item in img['srcset'].split(',')]
        candidates = {local_target(path, url)[0] for url in urls}
        assets.update(candidates)
        page_bytes += max(asset.stat().st_size for asset in candidates)
    assert page_bytes <= PAGE_BUDGET, f'{path.name}: {page_bytes:,} bytes exceeds the page budget'
    print(f'PASS {path.name}: links and images checked; at most {page_bytes:,} / {PAGE_BUDGET:,} bytes')

image_files = {p.resolve() for p in (ROOT / 'images').iterdir() if p.is_file()}
assert assets == image_files, 'Remove unused image files'
print(f'PASS total HTML and assets: {sum(p.stat().st_size for p in set(pages) | assets):,} bytes; no JavaScript')

if '--build' in sys.argv:
    output = ROOT / '_site'
    assert not output.exists(), 'Build into a fresh _site directory'
    for source in set(pages) | assets:
        target = output / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print('Built _site with only the HTML pages and referenced images')
