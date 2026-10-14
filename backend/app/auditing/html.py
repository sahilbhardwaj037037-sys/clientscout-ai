from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


class Signals(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titles = []
        self.in_title = False
        self.title_parts = []
        self.descriptions = []
        self.canonicals = []
        self.viewport = []
        self.robots = []
        self.language = None
        self.h1_count = 0
        self.images = 0
        self.missing_alt = 0
        self.scripts = 0
        self.stylesheets = 0
        self.base_href = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'title':
            self.in_title = True
            self.title_parts = []
        elif tag == 'html':
            self.language = values.get('lang')
        elif tag == 'h1':
            self.h1_count += 1
        elif tag == 'img':
            self.images += 1
            self.missing_alt += 'alt' not in values
        elif tag == 'script' and values.get('src'):
            self.scripts += 1
        elif tag == 'base' and self.base_href is None:
            self.base_href = values.get('href')
        elif tag == 'meta':
            name = (values.get('name') or '').lower()
            content = values.get('content') or ''
            if name == 'description': self.descriptions.append(content)
            if name == 'viewport': self.viewport.append(content)
            if name in {'robots', 'googlebot'}: self.robots.append({'name': name, 'content': content})
        elif tag == 'link':
            relations = (values.get('rel') or '').lower().split()
            if 'canonical' in relations: self.canonicals.append(values.get('href') or '')
            if 'stylesheet' in relations: self.stylesheets += 1

    def handle_endtag(self, tag):
        if tag == 'title' and self.in_title:
            self.titles.append(' '.join(''.join(self.title_parts).split())[:1000])
            self.in_title = False

    def handle_data(self, data):
        if self.in_title: self.title_parts.append(data[:1000])


def analyze_html(body, url, headers):
    parser = Signals()
    # Declared charset is honored where supported; replacement chars are reported.
    import re
    charset = re.search(r'charset=["\']?([\w-]+)', headers.get('content-type', ''), re.I)
    encoding = charset.group(1) if charset else 'utf-8'
    try: text = body.decode(encoding, 'replace')
    except LookupError: text = body.decode('utf-8', 'replace'); encoding = 'utf-8 (fallback)'
    parser.feed(text)
    def safe_join(base_url, relative):
        try: return urljoin(base_url, relative)
        except ValueError: return None
    base = safe_join(url, parser.base_href) if parser.base_href else url
    base = base or url
    canonicals = [{'raw': value[:2048], 'resolved': (safe_join(base, value) or '')[:2048] or None if value else None} for value in parser.canonicals[:20]]
    signals = {'titles': parser.titles[:20], 'meta_descriptions': [value[:2000] for value in parser.descriptions[:20]],
               'canonicals': canonicals, 'viewport': parser.viewport[:20], 'robots_meta': parser.robots[:20],
               'x_robots_tag': headers.get('x-robots-tag'), 'html_language': parser.language,
               'h1_count': parser.h1_count, 'images': parser.images, 'images_without_alt': parser.missing_alt,
               'external_scripts': parser.scripts, 'stylesheets': parser.stylesheets, 'decoded_charset': encoding,
               'decoding_replacements': text.count('\ufffd')}
    findings = []
    def finding(code, level, title, evidence, recommendation):
        findings.append({'code': code, 'level': level, 'title': title, 'evidence': evidence, 'source_url': url, 'recommendation': recommendation})
    if not parser.titles or not parser.titles[0]:
        finding('title_missing', 'attention', 'HTML title is missing or empty', 'No non-empty first <title> in the downloaded HTML.', 'Add a descriptive title for this page in the HTML head.')
    else:
        finding('title_present', 'observed', 'HTML title found', parser.titles[0], 'Check that this title describes the page accurately; presence alone does not establish SEO quality.')
    if len(parser.titles) > 1:
        finding('title_multiple', 'attention', 'Multiple HTML titles', f'{len(parser.titles)} title tags.', 'Keep one authoritative title in the document head.')
    if not parser.descriptions or not parser.descriptions[0].strip():
        finding('description_missing', 'attention', 'Meta description missing or empty', 'No non-empty first meta[name=description] in the downloaded HTML.', 'Add a useful page-specific summary; search engines may still choose a different snippet.')
    else:
        finding('description_present', 'observed', 'Meta description found', parser.descriptions[0][:2000], 'Review relevance and clarity; this is not a ranking prediction.')
    if len(parser.descriptions) > 1:
        finding('description_multiple', 'attention', 'Multiple meta descriptions', f'{len(parser.descriptions)} description tags.', 'Use one page-specific meta description.')
    if not canonicals:
        finding('canonical_missing', 'review', 'No canonical tag observed', 'No link[rel=canonical] in the downloaded HTML.', 'Consider a canonical URL if alternate URLs can show duplicate content; absence alone is not an error.')
    for canonical in canonicals:
        resolved = canonical['resolved']
        if not resolved or urlsplit(resolved).scheme not in {'http', 'https'}:
            finding('canonical_invalid', 'attention', 'Canonical URL is empty or has an unsupported scheme', canonical['raw'], 'Use an absolute public HTTP/HTTPS canonical for the intended page.')
    if len(parser.canonicals) > 1:
        finding('canonical_multiple', 'attention', 'Multiple canonical tags', f'{len(parser.canonicals)} canonical tags.', 'Choose a single intended canonical URL.')
    if parser.h1_count != 1:
        finding('h1_review', 'review', 'Review the main heading structure', f'{parser.h1_count} H1 elements in static HTML.', 'Review whether the page has a clear main heading; the count is not an SEO score.')
    if not parser.language:
        finding('language_missing', 'attention', 'Document language is missing', 'The <html> element has no non-empty lang attribute.', 'Set the document language to help assistive technologies.')
    if not any('width=device-width' in value.lower().replace(' ', '') for value in parser.viewport):
        finding('viewport_missing', 'attention', 'Responsive viewport signal not observed', str(parser.viewport)[:2000], 'Review adding a width=device-width viewport. A viewport tag alone does not prove mobile usability.')
    else:
        finding('viewport_present', 'observed', 'Responsive viewport declaration found', str(parser.viewport)[:2000], 'Verify the rendered page on real mobile devices; static HTML cannot measure layout.')
    if parser.missing_alt:
        finding('image_alt_missing', 'attention', 'Images without an alt attribute', f'{parser.missing_alt} of {parser.images} static img elements lack alt attributes.', 'Add useful alternative text for informative images; use alt="" for decorative images.')
    directives = ' '.join(item['content'] for item in parser.robots) + ' ' + headers.get('x-robots-tag', '')
    if 'noindex' in directives.lower():
        finding('noindex_observed', 'review', 'A noindex directive was observed', directives[:2000], 'Confirm this is intentional. Remove it only if this page should be indexed.')
    return signals, findings
