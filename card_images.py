"""Best-effort discovery of a card image from a public web page."""
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


def _likely_brand_image(url, description=''):
    text = unquote(urlsplit(url).path + ' ' + urlsplit(url).query) + ' ' + description
    return bool(re.search(r'logo|favicon|\bicons?\b|avatar|sprite|placeholder|tracking|\bpixel\b', text, re.I))


def _public_page(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
        raise ValueError('Not a public web URL')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Not a public web address')


class _PublicRedirects(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public_page(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Images(HTMLParser):
    def __init__(self, page_url):
        super().__init__()
        self.base = page_url
        self.social = {}
        self.candidates = []
        self.content_depth = 0
        self.last_social = None
        self.rejected = set()

    def _url(self, value):
        if not value or not value.strip():
            return ''
        candidate = urljoin(self.base, value.strip())
        parsed = urlsplit(candidate)
        return candidate if parsed.scheme in ('http', 'https') and parsed.hostname else ''

    @property
    def image(self):
        for key in ('og:image', 'og:image:url', 'twitter:image', 'twitter:image:src'):
            for image in self.social.get(key, []):
                if (image['url'] not in self.rejected
                        and not _likely_brand_image(image['url'], image.get('alt', ''))
                        and not any(image.get(d, 100) < 100 for d in ('width', 'height'))):
                    return image['url']
        if self.candidates:
            # Prefer images inside main/article, then the largest known image.
            return max(self.candidates, key=lambda entry: entry[:2])[2]
        return ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('main', 'article'):
            self.content_depth += 1
        if tag == 'base' and attrs.get('href'):
            self.base = urljoin(self.base, attrs['href'])
        if tag == 'meta':
            key = (attrs.get('property') or attrs.get('name') or '').lower()
            if key in ('og:image', 'og:image:url', 'twitter:image', 'twitter:image:src'):
                candidate = self._url(attrs.get('content'))
                self.last_social = {'url': candidate, 'key': key}
                if candidate:
                    self.social.setdefault(key, []).append(self.last_social)
            elif self.last_social:
                prefix = 'og:image' if self.last_social['key'].startswith('og:') else 'twitter:image'
                if key == prefix + ':alt':
                    self.last_social['alt'] = attrs.get('content') or ''
                elif key in (prefix + ':width', prefix + ':height'):
                    try:
                        self.last_social[key.rsplit(':', 1)[1]] = float(attrs.get('content') or '')
                    except ValueError:
                        pass
        if tag != 'img':
            return
        dimensions = []
        for attribute in ('width', 'height'):
            match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)(?:px)?\s*', attrs.get(attribute) or '')
            dimensions.append(float(match[1]) if match else None)
        if any(value is not None and value < 100 for value in dimensions):
            return
        # Lazy-loaded pages often put the actual image in data-src.
        for key in ('data-src', 'data-original', 'src'):
            candidate = self._url(attrs.get(key))
            if not candidate:
                continue
            description = ' '.join([unquote(urlsplit(candidate).path)] +
                                   [attrs.get(k) or '' for k in ('alt', 'class', 'id', 'role')])
            if _likely_brand_image(candidate, description):
                self.rejected.add(candidate)
                continue
            area = dimensions[0] * dimensions[1] if all(dimensions) else 0
            self.candidates.append((self.content_depth > 0, area, candidate))
            break

    def handle_endtag(self, tag):
        if tag in ('main', 'article'):
            self.content_depth = max(0, self.content_depth - 1)


def discover_card_image(page_url):
    """Prefer social preview metadata, then a likely content image."""
    if not page_url.strip():
        return ''
    try:
        _public_page(page_url)
        opener = build_opener(ProxyHandler({}), _PublicRedirects())
        request = Request(page_url, headers={'User-Agent': 'GroupVoting/1.0', 'Accept': 'text/html,image/*'})
        with opener.open(request, timeout=5) as response:
            if response.headers.get_content_type().startswith('image/'):
                return response.geturl()
            if response.headers.get_content_type() not in ('text/html', 'application/xhtml+xml'):
                return ''
            parser = _Images(response.geturl())
            parser.feed(response.read(1_000_000).decode(response.headers.get_content_charset() or 'utf-8', errors='replace'))
            return parser.image
    except (OSError, ValueError, LookupError):
        return ''
