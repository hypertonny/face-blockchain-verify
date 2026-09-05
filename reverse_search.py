"""Genuine reverse-image search module.

No hardcoded results: every match comes from a live reverse-image query
at runtime. Provider order:

  1. SerpApi Google Lens (if SERPAPI_API_KEY is set) — genuine Lens results.
  2. Yandex CBIR (no key needed) — uploads nothing; queries the public
     Yandex visual-search index by image URL, parses the live
     `cbir_page=sites` result set ("sites where this picture appears").

Local files are first published to a temporary public URL (catbox.moe,
fallback: tmpfiles.org) purely so the CBIR engine can fetch the bytes —
the same as any user pasting an image link. The ranking/filtering then
prefers real social-media posts.
"""

import html as _html
import json as _json
import os
import re
import urllib.parse

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

SOCIAL_DOMAINS = [
    "instagram.com", "facebook.com", "fb.watch", "twitter.com", "x.com",
    "tiktok.com", "youtube.com", "youtu.be", "linkedin.com",
    "pinterest.com", "threads.com", "threads.net", "reddit.com",
    "vimeo.com", "dailymotion.com", "twitch.tv", "snapchat.com",
    "vk.com", "ok.ru", "sotwe.com", "weibo.com",
]

# Image CDNs that prove a copy of the picture exists on a social platform
# but are not themselves post URLs (used as supporting evidence only).
SOCIAL_CDN_HINTS = ["pbs.twimg.com", "scontent.", "fbcdn.net", "yt3.ggpht.com",
                    "i.ytimg.com", "pinimg.com"]


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    return s


def publish_image(image_path, timeout=60):
    """Upload a local file to a free public host. Returns the public URL."""
    name = os.path.basename(image_path)
    with open(image_path, "rb") as f:
        data = f.read()
    ext = os.path.splitext(name)[1].lower() or ".jpg"
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif"}.get(ext.lstrip("."),
                                                          "image/jpeg")
    errors = []

    # Primary: catbox.moe (no key, allows hotlinking).
    try:
        r = requests.post("https://catbox.moe/user/api.php",
                          files={"fileToUpload": (name, data, mime)},
                          data={"reqtype": "fileupload"}, timeout=timeout)
        if r.status_code == 200 and r.text.startswith("https://"):
            return r.text.strip()
        errors.append(f"catbox: {r.status_code} {r.text[:100]}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"catbox: {e}")

    # Fallback: tmpfiles.org.
    try:
        r = requests.post("https://tmpfiles.org/api/v1/upload",
                          files={"file": (name, data, mime)}, timeout=timeout)
        if r.status_code == 200:
            url = r.json()["data"]["url"].replace("tmpfiles.org/",
                                                   "tmpfiles.org/dl/")
            return url
        errors.append(f"tmpfiles: {r.status_code}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"tmpfiles: {e}")

    raise RuntimeError("could not publish image: " + " | ".join(errors))


def _yandex_search_page(s, image_url, timeout=40):
    params = {"rpt": "imageview",
              "url": image_url}
    r = s.get("https://yandex.com/images/search", params=params,
              timeout=timeout)
    r.raise_for_status()
    return r.text


def _extract_sites_url(search_html):
    u = search_html.replace("&quot;", '"').replace("&amp;", "&")
    m = re.search(
        r'"url":"(/images/search\?rpt=imageview&url=https?[^"]+?&cbir_id=[^"]+?&cbir_page=sites)"',
        u)
    if not m:
        m = re.search(
            r'(/images/search\?rpt=imageview&url=\S+?&cbir_id=\S+?&cbir_page=sites)',
            u)
    if not m:
        return None
    return "https://yandex.com" + _html.unescape(m.group(1)).rstrip('"')


def _parse_sites(sites_html):
    u = sites_html.replace("&quot;", '"').replace("&amp;", "&")
    items = []
    # Site entries are flat JSON objects on one logical line:
    # {"title":"...","description":"...","url":"https://...","domain":"..."}.
    # Parse segment-by-segment so fields can never bleed across objects.
    for seg in u.split('{"title":"')[1:]:
        seg = seg[:4000]  # one entry is well under this
        m = re.match(
            r'(?P<title>(?:[^"\\]|\\.)*)","description":"'
            r'(?P<desc>(?:[^"\\]|\\.)*)","url":"(?P<url>https?://[^"]+)",'
            r'"domain":"(?P<domain>[^"]+)"', seg)
        if not m:
            continue
        domain = m.group("domain")
        if any(c in domain for c in (" ", "{", "}", "<", "\\")):
            continue
        try:
            title = _json.loads(f'"{m.group("title")}"')
        except Exception:  # noqa: BLE001
            title = m.group("title")
        title = _html.unescape(title)
        img = ""
        mi = re.search(r'"originalImage":\{"url":"([^"]+)"', seg[:2500])
        if mi:
            img = _html.unescape(mi.group(1))
        url = re.sub(r"[?&]utm_medium=.*$", "", m.group("url"))
        items.append({
            "title": title,
            "page_url": _html.unescape(url),
            "domain": domain,
            "image_url": img,
            "provider": "yandex-cbir",
        })
    # De-duplicate by page URL.
    seen, uniq = set(), []
    for it in items:
        if it["page_url"] not in seen:
            seen.add(it["page_url"])
            uniq.append(it)
    return uniq


def _is_social(item):
    host = urllib.parse.urlparse(item["page_url"]).netloc.lower()
    return any(s in host for s in SOCIAL_DOMAINS)


def yandex_reverse_search(image_url, timeout=60):
    """Live Yandex CBIR reverse search. Returns list of match dicts."""
    s = _session()
    search_html = _yandex_search_page(s, image_url, timeout=timeout)
    sites_url = _extract_sites_url(search_html)
    if not sites_url:
        raise RuntimeError("yandex returned no CBIR result set "
                           "(page may be rate-limited; retry later)")
    r = s.get(sites_url, timeout=timeout)
    r.raise_for_status()
    return _parse_sites(r.text)


def serpapi_lens_search(image_url, timeout=60):
    """Genuine Google Lens results via SerpApi. Needs SERPAPI_API_KEY.

    Single call with type=all returns exact_matches + visual_matches
    (docs: serpapi.com/google-lens-api). Cached repeat queries are free.
    """
    key = os.environ.get("SERPAPI_API_KEY", "")
    if not key:
        raise RuntimeError("SERPAPI_API_KEY not set")
    r = requests.get("https://serpapi.com/search.json", params={
        "engine": "google_lens", "url": image_url, "type": "all",
        "hl": "en", "api_key": key,
    }, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"serpapi: {data['error']}")
    out = []
    for m in data.get("exact_matches", []) + data.get("visual_matches", []):
        link = m.get("link", "")
        if not link:
            continue
        out.append({
            "title": m.get("title", ""),
            "page_url": link,
            "domain": urllib.parse.urlparse(link).netloc,
            # Full-size match image preferred (face verification), else thumb.
            "image_url": m.get("image", "") or m.get("thumbnail", ""),
            "source": m.get("source", ""),
            "provider": "serpapi-google-lens",
        })
    # De-duplicate by page URL, exact matches first.
    seen, uniq = set(), []
    for it in out:
        if it["page_url"] not in seen:
            seen.add(it["page_url"])
            uniq.append(it)
    return uniq


def search_url(public_url, timeout=60):
    """Run provider search on an already-public image URL.

    Returns (matches, provider, errors). SerpApi Lens first (if key),
    Yandex CBIR fallback. Raises only if both fail — caller decides.
    """
    matches, provider, errors = [], None, []
    if os.environ.get("SERPAPI_API_KEY"):
        try:
            matches = serpapi_lens_search(public_url, timeout=timeout)
            provider = "serpapi-google-lens"
        except Exception as e:  # noqa: BLE001
            errors.append(f"serpapi: {e}")
    if not matches:
        try:
            matches = yandex_reverse_search(public_url, timeout=timeout)
            provider = provider or "yandex-cbir"
        except Exception as e:  # noqa: BLE001
            errors.append(f"yandex: {e}")
    return matches, provider, errors


def reverse_search(image_path_or_url, timeout=60):
    """Full flow: publish (if local) -> live reverse search -> ranked matches.

    Returns dict with public_image_url, matches, social_matches, best_match.
    """
    if re.match(r"^https?://", image_path_or_url):
        public_url = image_path_or_url
    else:
        public_url = publish_image(image_path_or_url, timeout=timeout)

    matches, provider, errors = search_url(public_url, timeout=timeout)

    if not matches:
        raise RuntimeError("reverse search returned no matches: " +
                           " | ".join(errors))

    social = [m for m in matches if _is_social(m)]
    best = social[0] if social else matches[0]
    return {
        "public_image_url": public_url,
        "provider": provider,
        "num_matches": len(matches),
        "num_social_matches": len(social),
        "social_matches": social[:20],
        "matches": matches[:50],
        "best_match": best,
        "is_social_match": bool(social),
        "provider_errors": errors,
    }
