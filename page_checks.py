"""Extra per-page checks for the crawler.

Pure stdlib plus BeautifulSoup: no network, deterministic. The crawler calls
``extra_issues()`` once per page and extends ``result['issues']`` with whatever
comes back, so every check here can be tested offline against a fixture string
rather than a live page.

Why these and not more: each one is a signal Google acts on that the crawler
did not already report. Checks that only lint the markup, or that need a second
request, are left out on purpose.

The head-position checks read the raw HTML rather than the parsed tree.
html.parser keeps a tag wherever the markup put it, while a browser closes
<head> at the first element that does not belong there and moves everything
after it into <body>. A canonical or robots tag that lands in the body is
ignored by Google, which is the whole point of the check, so the raw byte
positions are what matters.
"""

import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin

# Tags allowed inside <head>. The first tag outside this set closes the head in
# every browser, whatever the markup claims. <template> is allowed too but is
# rare enough in a head that it is not worth the false-negative risk.
_HEAD_TAGS = {'title', 'meta', 'link', 'script', 'style', 'base', 'noscript'}

# Helvetica AFM advance widths in 1/1000 em. Arial matches these closely enough
# for a truncation estimate, and Google renders SERP titles in Arial.
_W = {
    ' ': 278, '!': 278, '"': 355, '#': 556, '$': 556, '%': 889, '&': 667,
    "'": 191, '(': 333, ')': 333, '*': 389, '+': 584, ',': 278, '-': 333,
    '.': 278, '/': 278, ':': 278, ';': 278, '<': 584, '=': 584, '>': 584,
    '?': 556, '@': 1015, '[': 278, '\\': 278, ']': 278, '^': 469, '_': 556,
    '`': 333, '{': 334, '|': 260, '}': 334, '~': 584,
    'A': 667, 'B': 667, 'C': 722, 'D': 722, 'E': 667, 'F': 611, 'G': 778,
    'H': 722, 'I': 278, 'J': 500, 'K': 667, 'L': 556, 'M': 833, 'N': 722,
    'O': 778, 'P': 667, 'Q': 778, 'R': 722, 'S': 667, 'T': 611, 'U': 722,
    'V': 667, 'W': 944, 'X': 667, 'Y': 667, 'Z': 611,
    'a': 556, 'b': 556, 'c': 500, 'd': 556, 'e': 556, 'f': 278, 'g': 556,
    'h': 556, 'i': 222, 'j': 222, 'k': 500, 'l': 222, 'm': 833, 'n': 556,
    'o': 556, 'p': 556, 'q': 556, 'r': 333, 's': 500, 't': 278, 'u': 556,
    'v': 500, 'w': 722, 'x': 500, 'y': 500, 'z': 500,
}
for _d in '0123456789':
    _W[_d] = 556

# Google truncates a desktop title around 580px (Arial 20px) and a description
# around 920px (Arial 14px). Same numbers the commercial tools use.
TITLE_PX_LIMIT = 580
DESC_PX_LIMIT = 920

# The width table is an estimate: Arial stands in for whatever Google renders,
# and it takes no account of bold or of a locale's own font. Across a large
# sample of real pages the median title that passes 580px measures about 590px
# and the median description about 939px, so reporting from the limit itself
# would flag page after page that loses a character or two at most. These are
# the points where truncation is past any doubt, and the wording stays
# "may truncate".
TITLE_PX_REPORT = 620
DESC_PX_REPORT = 990

# Junk a template writes into a URL when a variable never resolved. Seen live on
# 412 pages of one site as "https://www.example.comundefined".
#
# Matched only at the end of the URL or as a whole segment, never as a bare
# substring: "/blog/undefined-behaviour" is a real article, and "annulled"
# contains the letters of null.
_JUNK_URL_RES = (
    re.compile(r'(?:undefined|null|NaN)[/]?\s*$', re.I),
    re.compile(r'[/?&=](?:undefined|null|NaN)(?:[/?&#]|$)', re.I),
    re.compile(r'\[object|%5Bobject|%7Bundefined', re.I),
)


def _url_junk(value):
    """True when a URL carries an unresolved template variable."""
    return any(rx.search(value or '') for rx in _JUNK_URL_RES)

_LANG_RE = re.compile(r'^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$')
_REGION_RE = re.compile(r'^[A-Za-z]{2}$|^[0-9]{3}$')

# Wording that means "this page is not here", checked against title and H1.
_SOFT_404_RE = re.compile(
    r'\b(404|page not found|not found|page (?:does|doesn\'?t) exist|'
    r'page (?:is )?(?:no longer|unavailable)|nothing (?:was )?found|'
    r'page (?:has been )?removed|error 404)\b', re.I)


def text_px(text, size):
    """Approximate rendered width of ``text`` in px at ``size`` px Arial."""
    total = 0
    for ch in text or '':
        total += _W.get(ch, 556)
    return round(total * size / 1000)


def _head_cut(raw_html):
    """Byte offset where a browser closes <head>, or None when it runs to </head>.

    Returns the offset of the first tag that forces the head shut. Comments,
    whitespace and the head tags themselves do not.
    """
    if not raw_html:
        return None
    head_open = re.search(r'<head[\s>]', raw_html, re.I)
    start = head_open.end() if head_open else 0
    end_m = re.search(r'</head\s*>', raw_html, re.I)
    end = end_m.start() if end_m else len(raw_html)
    # Blank out comments so a commented-out <div> cannot close the head.
    region = raw_html[start:end]
    region = re.sub(r'<!--.*?-->', lambda m: ' ' * len(m.group(0)), region,
                    flags=re.S)
    for m in re.finditer(r'<(/?)([a-zA-Z][a-zA-Z0-9-]*)', region):
        if m.group(1):          # a closing tag never opens body content
            continue
        if m.group(2).lower() in _HEAD_TAGS:
            continue
        return start + m.start()
    return None


def _positions(raw_html, pattern):
    """Offsets of every match of ``pattern`` in the raw HTML."""
    return [m.start() for m in re.finditer(pattern, raw_html or '', re.I)]


def _http_date_past(value):
    """True when ``value`` parses as a date already gone by."""
    value = (value or '').strip()
    for fmt in ('%Y-%m-%d', '%d %b %Y', '%d-%b-%Y', '%Y-%m-%dT%H:%M:%S%z',
                '%a, %d %b %Y %H:%M:%S %Z', '%a, %d %b %Y %H:%M:%S %z'):
        try:
            dt = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt < datetime.now(timezone.utc)
    return False


def head_issues(raw_html):
    """Directives a browser would move out of <head>, so Google ignores them."""
    out = []
    cut = _head_cut(raw_html)
    if cut is None:
        return out
    checks = (
        (r'<title[\s>]', 'Title'),
        (r'<link[^>]+rel\s*=\s*["\']?canonical', 'Canonical'),
        (r'<meta[^>]+name\s*=\s*["\']?robots', 'Meta robots'),
        (r'<meta[^>]+name\s*=\s*["\']?description', 'Meta description'),
        (r'<link[^>]+hreflang\s*=', 'Hreflang'),
    )
    for pattern, label in checks:
        hits = [p for p in _positions(raw_html, pattern) if p > cut]
        if hits:
            out.append(f'{label} outside head (Google ignores it)')
    return out


def duplicate_tag_issues(soup):
    """More than one of a tag that may only appear once."""
    out = []
    titles = soup.find_all('title')
    if len(titles) > 1:
        out.append(f'Multiple title tags ({len(titles)})')
    cans = soup.find_all('link', attrs={'rel': 'canonical'})
    if len(cans) > 1:
        hrefs = {(c.get('href') or '').strip() for c in cans}
        if len(hrefs) > 1:
            out.append(f'Multiple conflicting canonicals ({len(cans)})')
        else:
            out.append(f'Multiple canonical tags ({len(cans)})')
    descs = soup.find_all('meta', attrs={'name': re.compile(r'^description$', re.I)})
    if len(descs) > 1:
        out.append(f'Multiple meta descriptions ({len(descs)})')
    vps = soup.find_all('meta', attrs={'name': re.compile(r'^viewport$', re.I)})
    if len(vps) > 1:
        out.append(f'Multiple viewport tags ({len(vps)})')
    return out


def canonical_issues(result, headers, soup):
    """Canonical conflicts a single tag read cannot show."""
    out = []
    page_url = result.get('url') or ''
    canonical = (result.get('canonical') or '').strip()
    kind = result.get('canonical_kind')

    link_hdr = headers.get('link', '') or ''
    hdr_canon = ''
    for part in link_hdr.split(','):
        if 'rel="canonical"' in part.replace(' ', '').replace("'", '"') \
                or 'rel=canonical' in part.replace(' ', ''):
            m = re.search(r'<([^>]+)>', part)
            if m:
                hdr_canon = m.group(1).strip()
                break
    if hdr_canon and canonical:
        a = urljoin(page_url, canonical).rstrip('/')
        b = urljoin(page_url, hdr_canon).rstrip('/')
        if a != b:
            out.append('Canonical conflict: HTML and HTTP header disagree')
    elif hdr_canon and not canonical:
        out.append('Canonical only in the HTTP header (easy to miss on edit)')

    if canonical:
        abs_can = urljoin(page_url, canonical)
        # A template that printed an unresolved variable comes first: the URL is
        # broken, so calling it cross-domain or relative would mislead.
        if _url_junk(canonical):
            out.append(f'Canonical is malformed ("{canonical[-40:]}")')
            return out
        if abs_can.startswith('http://') and page_url.startswith('https://'):
            out.append('Canonical points to HTTP from an HTTPS page')
        if not re.match(r'^https?://', canonical.strip(), re.I):
            out.append('Canonical is a relative URL')
        if kind == 'canonicalised' and not result.get('indexable', True):
            out.append('Noindex plus a canonical to another URL (conflicting signals)')
        try:
            can_host = urlparse(abs_can).netloc.lower().replace('www.', '')
            page_host = urlparse(page_url).netloc.lower().replace('www.', '')
            if can_host and page_host and can_host != page_host:
                out.append(f'Canonical points to another host ({can_host})')
        except ValueError:
            pass
    return out


def directive_issues(soup, headers, result):
    """Robots directives beyond the plain noindex the crawler already reports."""
    out = []
    parts = []
    tag = soup.find('meta', attrs={'name': re.compile(r'^robots$', re.I)})
    if tag:
        parts.append((tag.get('content') or '').lower())
    xrt = (headers.get('x-robots-tag') or '').lower()
    if xrt:
        parts.append(xrt)
        if 'noindex' in xrt:
            out.append('noindex in the X-Robots-Tag header')
    joined = ' '.join(parts)
    tokens = {t.strip() for chunk in joined.split(',') for t in chunk.split()}

    if 'noindex' in joined and re.search(r'(^|[\s,])index([\s,]|$)', joined):
        out.append('Conflicting robots directives (index and noindex)')
    if 'none' in tokens:
        out.append('Robots "none" (same as noindex, nofollow)')
    if 'nosnippet' in tokens:
        out.append('nosnippet (no text snippet in results)')
    if 'noarchive' in tokens:
        out.append('noarchive (no cached copy)')
    m = re.search(r'unavailable_after\s*:\s*([^,\'"]+)', joined)
    if m and _http_date_past(m.group(1)):
        out.append('unavailable_after date has passed (dropped from results)')
    return out


def soft_404_issues(result):
    """A 200 response that reads like an error page."""
    status = result.get('status_code') or 0
    if not (200 <= status < 300):
        return []
    title = result.get('title') or ''
    h1 = result.get('h1') or ''
    if not _SOFT_404_RE.search(title) and not _SOFT_404_RE.search(h1):
        return []
    if (result.get('word_count') or 0) > 350:
        return []
    # A WordPress term archive for a term that happens to read like an error
    # ("404 Archives | Site", seen on a spec-value archive) is a real page.
    if re.search(r'\barchives?\b', title, re.I):
        return []
    where = 'title' if _SOFT_404_RE.search(title) else 'H1'
    return [f'Soft 404: returns 200 but the {where} says the page is missing']


def pixel_issues(result):
    """SERP truncation by rendered width, which character counts miss."""
    out = []
    title = result.get('title') or ''
    desc = result.get('meta_description') or ''
    # Only speak up when the character check stayed quiet, so a long title is
    # not reported twice in different units.
    if title and len(title) <= 60:
        px = text_px(title, 20)
        if px > TITLE_PX_REPORT:
            out.append(f'Title may truncate in results (about {px}px, limit {TITLE_PX_LIMIT})')
    if desc and len(desc) <= 150:
        px = text_px(desc, 14)
        if px > DESC_PX_REPORT:
            out.append(f'Meta description may truncate in results (about {px}px, limit {DESC_PX_LIMIT})')
    return out


def hreflang_issues(result):
    """Cluster faults visible from one page.

    A page whose canonical points elsewhere is skipped: Shopify variant URLs and
    ?page=2 archives carry the canonical page's hreflang set, so demanding a
    self-reference on this URL would be wrong. The cluster belongs to the
    canonical and is judged when that page is crawled.
    """
    entries = result.get('hreflang') or []
    if not entries or result.get('canonical_kind') == 'canonicalised':
        return []
    out = []
    page_url = (result.get('url') or '').rstrip('/')
    codes = {}
    bad_codes = []
    has_self = False
    for e in entries:
        code = (e.get('lang') or '').strip()
        href = (e.get('href') or '').strip()
        low = code.lower()
        if low != 'x-default':
            base = code.split('-')[0]
            region = code.split('-')[1] if '-' in code else ''
            if not _LANG_RE.match(code.lower()) or len(base) > 3 or \
                    (region and not _REGION_RE.match(region)):
                bad_codes.append(code)
        codes.setdefault(low, set()).add(href.rstrip('/'))
        if href.rstrip('/') == page_url:
            has_self = True
    if bad_codes:
        out.append(f'Invalid hreflang code ({", ".join(sorted(set(bad_codes))[:3])})')
    dupes = [c for c, hrefs in codes.items() if len(hrefs) > 1]
    if dupes:
        out.append(f'Duplicate hreflang code with different URLs ({", ".join(sorted(dupes)[:3])})')
    if not has_self:
        out.append('No self-referencing hreflang entry')
    lang = (result.get('html_lang') or '').strip().lower()
    if lang and has_self:
        selves = [c for c, hrefs in codes.items() if page_url in hrefs and c != 'x-default']
        if selves and not any(c.split('-')[0] == lang.split('-')[0] for c in selves):
            out.append(f'HTML lang "{lang}" does not match its own hreflang entry')
    canonical = (result.get('canonical') or '').strip()
    if canonical and result.get('canonical_kind') == 'self':
        all_hrefs = {h for hrefs in codes.values() for h in hrefs}
        if urljoin(result.get('url') or '', canonical).rstrip('/') not in all_hrefs:
            out.append('Canonical URL is missing from the hreflang set')
    return out


def lang_issues(soup, result):
    """Language declaration on <html>."""
    out = []
    html_tag = soup.find('html')
    lang = ((html_tag.get('lang') if html_tag else '') or '').strip()
    result['html_lang'] = lang
    if not lang:
        out.append('No lang attribute on <html>')
    elif not _LANG_RE.match(lang.lower()):
        out.append(f'Invalid lang attribute ("{lang[:20]}")')
    return out


def heading_issues(result, soup):
    """Heading faults past the missing and multiple H1 the crawler reports."""
    out = []
    h1 = result.get('h1') or ''
    if len(h1) > 70:
        out.append(f'H1 too long ({len(h1)} chars)')
    levels = []
    for tag in soup.find_all(re.compile(r'^h[1-6]$', re.I)):
        if tag.get_text(strip=True):
            levels.append(int(tag.name[1]))
    if levels:
        if levels[0] != 1:
            out.append(f'First heading is H{levels[0]}, not H1')
        for prev, nxt in zip(levels, levels[1:]):
            if nxt > prev + 1:
                out.append(f'Heading level skips (H{prev} to H{nxt})')
                break
    return out


def link_issues(soup, result, page_url, domain):
    """Internal link faults: insecure targets, nofollow, dead page anchors."""
    out = []
    is_https = (result.get('security') or {}).get('is_https')
    http_internal = 0
    nofollow_internal = 0
    frags = []
    for a in soup.find_all('a', href=True):
        href = (a.get('href') or '').strip()
        if not href:
            continue
        if href.startswith('#'):
            if len(href) > 1:
                frags.append(href[1:])
            continue
        if re.match(r'^(mailto|tel|javascript|sms|data|file):', href, re.I):
            continue
        resolved = urljoin(page_url, href)
        try:
            host = urlparse(resolved).netloc.lower().replace('www.', '')
        except ValueError:
            continue
        if host != domain:
            continue
        if is_https and resolved.startswith('http://'):
            http_internal += 1
        rel = a.get('rel') or []
        rel_str = ' '.join(rel).lower() if isinstance(rel, list) else str(rel).lower()
        if 'nofollow' in rel_str:
            nofollow_internal += 1
    if http_internal:
        out.append(f'{http_internal} internal link(s) point to HTTP')
    if nofollow_internal:
        out.append(f'{nofollow_internal} internal link(s) are nofollow')
    if frags:
        ids = {el.get('id') for el in soup.find_all(attrs={'id': True})}
        ids |= {el.get('name') for el in soup.find_all('a', attrs={'name': True})}
        missing = sorted({f for f in frags if f not in ids and f.lower() != 'top'})
        if missing:
            shown = ', '.join('#' + f for f in missing[:3])
            out.append(f'{len(missing)} on-page anchor(s) point to nothing ({shown})')
    return out


def delivery_issues(headers, raw_html):
    """Transfer-level faults that cost crawl time on every request."""
    out = []
    enc = (headers.get('content-encoding') or '').lower()
    if not enc and raw_html and len(raw_html) > 50_000:
        out.append('No compression (gzip or brotli) on a large page')
    if 'cache-control' not in headers and 'expires' not in headers:
        out.append('No cache-control header')
    return out


def markup_issues(raw_html, soup):
    """Document faults that change how the page is parsed."""
    out = []
    head = raw_html[:2000] if raw_html else ''
    if raw_html and not re.search(r'<!doctype\s+html', head, re.I):
        out.append('No doctype (renders in quirks mode)')
    if len(soup.find_all('head')) > 1:
        out.append('Multiple head elements')
    if len(soup.find_all('body')) > 1:
        out.append('Multiple body elements')
    charset = None
    m = soup.find('meta', attrs={'charset': True})
    if m:
        charset = (m.get('charset') or '').strip().lower()
    else:
        m = soup.find('meta', attrs={'http-equiv': re.compile(r'^content-type$', re.I)})
        if m:
            cm = re.search(r'charset\s*=\s*([\w-]+)', m.get('content') or '', re.I)
            charset = cm.group(1).lower() if cm else None
    if charset is None:
        out.append('No charset declared')
    elif charset not in ('utf-8', 'utf8'):
        out.append(f'Charset is {charset}, not UTF-8')
    return out


def dom_issues(soup):
    """DOM weight, which drives render and interaction cost."""
    count = len(soup.find_all(True))
    if count > 1500:
        return [f'Large DOM ({count} elements)']
    return []


def image_issues(result):
    """Alt text long enough that a screen reader reads it as prose.

    150 chars, not the 100 the commercial tools use: at 100 chars roughly one
    page in twenty fires, mostly on captions that read perfectly well, while at
    150 it is under one in a hundred and those really do have a paragraph in the
    attribute.
    """
    long_alts = 0
    for img in (result.get('images_all_data') or []):
        alt = img.get('alt')
        if isinstance(alt, str) and len(alt) > 150:
            long_alts += 1
    if long_alts:
        return [f'{long_alts} image(s) with alt text over 150 chars']
    return []


def pagination_issues(result):
    """A paginated page that cannot be indexed hides the items it lists."""
    if not result.get('is_pagination'):
        return []
    out = []
    if not result.get('indexable', True):
        out.append('Paginated page set to noindex (its items stay undiscovered)')
    if result.get('canonical_kind') == 'canonicalised':
        out.append('Paginated page canonicalised to another URL')
    return out


def extra_issues(raw_html, soup, headers, result, page_url, domain,
                 content_checks=True):
    """Every check in this module, in one list, for ``result['issues']``.

    ``headers`` must already be lower-cased keys. ``content_checks`` mirrors the
    crawler's own gate: when a page is noindex, paginated, canonicalised
    elsewhere or the target of a redirect, its copy belongs to another URL, so
    the checks that judge copy are held back while the technical ones still run.

    Never raises: a check that trips over odd markup is skipped rather than
    failing the crawl.
    """
    out = []
    technical = (
        lambda: lang_issues(soup, result),
        lambda: head_issues(raw_html),
        lambda: duplicate_tag_issues(soup),
        lambda: canonical_issues(result, headers, soup),
        lambda: directive_issues(soup, headers, result),
        lambda: soft_404_issues(result),
        lambda: hreflang_issues(result),
        lambda: delivery_issues(headers, raw_html),
        lambda: markup_issues(raw_html, soup),
        lambda: dom_issues(soup),
        lambda: pagination_issues(result),
    )
    content = (
        lambda: pixel_issues(result),
        lambda: heading_issues(result, soup),
        lambda: link_issues(soup, result, page_url, domain),
        lambda: image_issues(result),
    )
    for fn in technical + (content if content_checks else ()):
        try:
            out.extend(fn() or [])
        except Exception:
            continue
    return out
