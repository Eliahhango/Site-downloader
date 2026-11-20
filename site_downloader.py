#!/usr/bin/env python3
"""
Site Downloader & React App Converter
======================================
1. Downloads entire websites with all assets (images, fonts, styles, scripts, CDN files).
2. Automatically converts downloaded sites into modern, production-ready Vite + React apps
   without destroying page structure, Webflow / GSAP animations, interactions, or styles.

Usage:
  # Download and automatically convert to a React app:
  python site_downloader.py https://example.com -o downloaded_site --to-react

  # Specify a custom React output directory:
  python site_downloader.py https://example.com -o downloaded_site --to-react my-react-app

  # Convert an already downloaded website directory into a React app:
  python site_downloader.py --convert-dir ./downloaded_site --react-out ./my-react-app
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
import pathlib
import posixpath
import re
import shutil
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Iterable
from urllib.parse import unquote, urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ASSET_ATTRS = {
    "img": ["src", "srcset"],
    "script": ["src"],
    "source": ["src", "srcset"],
    "video": ["src", "poster"],
    "audio": ["src"],
    "iframe": ["src"],
}

SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "#")
TRACKING_QUERY_PREFIXES = ("utm_", "fbclid", "gclid", "mc_")


# ============================================================================
# Logging & Network Helpers
# ============================================================================

def log(message: str) -> None:
    try:
        print(message)
    except OSError:
        fallback = message.encode("ascii", errors="backslashreplace").decode("ascii")
        print(fallback)


def normalize_url(raw_url: str) -> str:
    clean, _frag = urldefrag(raw_url)
    return clean.strip()


def is_http(url: str) -> bool:
    if not url:
        return False
    p = urlparse(url)
    return p.scheme in ("http", "https")


def normalize_netloc(parsed: urllib.parse.ParseResult) -> str:
    host = parsed.netloc.lower()
    if host.endswith(":80") and parsed.scheme == "http":
        host = host[:-3]
    elif host.endswith(":443") and parsed.scheme == "https":
        host = host[:-4]
    return host


def simplify_path(path: str) -> str:
    if not path:
        return "/"
    normalized = posixpath.normpath(path)
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized


def drop_tracking_query(query: str) -> str:
    if not query:
        return ""
    kept = []
    for part in query.split("&"):
        key = part.split("=", 1)[0].lower()
        if any(key.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        kept.append(part)
    return "&".join(kept)


def canonicalize_url(raw_url: str, keep_query: bool) -> str:
    raw_url = normalize_url(raw_url)
    p = urlparse(raw_url)
    scheme = p.scheme.lower()
    if not scheme or not p.netloc:
        return raw_url
    netloc = normalize_netloc(p)
    path = simplify_path(p.path)
    query = drop_tracking_query(p.query) if keep_query else ""
    return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")


def root_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def in_scope(url: str, root_host: str, include_related_hosts: bool, allow_external_pages: bool) -> bool:
    if allow_external_pages:
        return is_http(url)
    host = normalize_netloc(urlparse(url))
    if not host:
        return False
    if host == root_host or host == f"www.{root_host}" or root_host == f"www.{host}":
        return True
    if include_related_hosts:
        return root_domain(host) == root_domain(root_host)
    return False


def normalize_srcset(srcset: str) -> Iterable[str]:
    for part in srcset.split(","):
        candidate = part.strip().split(" ")[0]
        if candidate:
            yield candidate


def shorten_component(component: str, max_len: int = 120) -> str:
    if len(component) <= max_len:
        return component
    digest = hashlib.sha1(component.encode("utf-8", errors="ignore")).hexdigest()[:12]
    keep = max_len - 15
    return f"{component[:keep]}_{digest}"


def to_local_path(url: str, output_dir: pathlib.Path) -> pathlib.Path:
    p = urlparse(url)
    netloc = normalize_netloc(p)
    path = p.path or "/"

    if path.endswith("/"):
        path = path + "index.html"

    filename = posixpath.basename(path)
    if "." not in filename:
        path = path + "/index.html"

    safe_path = re.sub(r"[<>:\\|?*]", "_", path.lstrip("/"))
    safe_parts = [shorten_component(part) for part in safe_path.split("/") if part]
    safe_path = "/".join(safe_parts) if safe_parts else "index.html"
    local_path = output_dir / netloc / safe_path

    if len(str(local_path)) > 240:
        digest = hashlib.sha1(str(local_path).encode("utf-8", errors="ignore")).hexdigest()[:16]
        stem = shorten_component(local_path.stem, max_len=48)
        local_path = local_path.with_name(f"{stem}_{digest}{local_path.suffix}")

    return local_path


def save_content(resp: requests.Response, dest: pathlib.Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(resp.content)


def is_cloudflare_challenge(resp: requests.Response) -> bool:
    server = (resp.headers.get("Server") or "").lower()
    if "cloudflare" not in server:
        return False
    body = resp.text.lower()
    return "challenge-platform" in body or "just a moment" in body


# ============================================================================
# Asset & Link Extraction
# ============================================================================

def extract_asset_links(soup: BeautifulSoup, base_url: str) -> set[str]:
    assets: set[str] = set()
    for tag, attrs in ASSET_ATTRS.items():
        for node in soup.find_all(tag):
            for attr in attrs:
                value = node.get(attr)
                if not value:
                    continue
                if attr == "srcset":
                    for u in normalize_srcset(value):
                        assets.add(urljoin(base_url, u))
                else:
                    assets.add(urljoin(base_url, value))

    allowed_link_rels = {
        "stylesheet",
        "icon",
        "shortcut",
        "shortcut icon",
        "apple-touch-icon",
        "manifest",
        "preload",
        "modulepreload",
        "prefetch",
    }
    for node in soup.find_all("link", href=True):
        rel_val = node.get("rel")
        if isinstance(rel_val, list):
            rel_tokens = {token.lower() for token in rel_val}
        elif isinstance(rel_val, str):
            rel_tokens = {rel_val.lower()}
        else:
            rel_tokens = set()
        if not rel_tokens or rel_tokens.intersection(allowed_link_rels):
            assets.add(urljoin(base_url, node["href"]))

    # Meta tags (og:image, twitter:image)
    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or "").lower()
        if prop in ("og:image", "twitter:image") and meta.get("content"):
            assets.add(urljoin(base_url, meta["content"]))

    # CSS url() in style tags or inline styles
    style_text = " ".join([tag.get_text() for tag in soup.find_all("style")])
    for style_attr in soup.find_all(attrs={"style": True}):
        style_text += " " + style_attr.get("style", "")
    for match in re.finditer(r'url\s*\(\s*[\'"]?([^\'")]+)[\'"]?\s*\)', style_text):
        u = match.group(1).strip()
        if not u.startswith("data:"):
            assets.add(urljoin(base_url, u))

    return assets


def extract_page_links(soup: BeautifulSoup, base_url: str) -> set[str]:
    links: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(SKIP_SCHEMES):
            continue
        links.add(urljoin(base_url, href))

    for form in soup.find_all("form", action=True):
        action = form["action"].strip()
        if action and not action.startswith(SKIP_SCHEMES):
            links.add(urljoin(base_url, action))

    return links


def parse_sitemap_xml(xml_text: str) -> set[str]:
    found: set[str] = set()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return found
    for elem in root.iter():
        if elem.tag.endswith("loc") and elem.text:
            found.add(elem.text.strip())
    return found


def discover_sitemaps(start_url: str, session: requests.Session, timeout: int) -> set[str]:
    p = urlparse(start_url)
    base = f"{p.scheme}://{normalize_netloc(p)}"
    candidates = {
        f"{base}/sitemap.xml",
        f"{base}/sitemap_index.xml",
    }
    robots_url = f"{base}/robots.txt"

    try:
        resp = session.get(robots_url, timeout=timeout)
        if resp.ok:
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemap_url = line.split(":", 1)[1].strip()
                    if sitemap_url:
                        candidates.add(sitemap_url)
    except requests.RequestException:
        pass

    return candidates


def collect_urls_from_sitemaps(
    sitemap_urls: set[str],
    session: requests.Session,
    timeout: int,
    root_host: str,
    include_related_hosts: bool,
    allow_external_pages: bool,
) -> set[str]:
    pending = collections.deque(sorted(sitemap_urls))
    visited: set[str] = set()
    page_urls: set[str] = set()
    max_sitemap_docs = 100

    while pending and len(visited) < max_sitemap_docs:
        sitemap_url = pending.popleft()
        sitemap_url = canonicalize_url(sitemap_url, keep_query=False)

        if sitemap_url in visited or not is_http(sitemap_url):
            continue

        visited.add(sitemap_url)

        try:
            resp = session.get(sitemap_url, timeout=timeout)
        except requests.RequestException:
            continue

        if not resp.ok:
            continue

        found = parse_sitemap_xml(resp.text)

        for u in found:
            cu = canonicalize_url(u, keep_query=False)
            if not cu:
                continue
            if cu.endswith(".xml") and "sitemap" in cu:
                if cu not in visited:
                    pending.append(cu)
            elif in_scope(cu, root_host, include_related_hosts, allow_external_pages):
                page_urls.add(cu)

    return page_urls


# ============================================================================
# Crawler & Downloader
# ============================================================================

def download_site(
    start_url: str,
    output_dir: pathlib.Path,
    max_pages: int,
    delay: float,
    timeout: int,
    user_agent: str,
    include_related_hosts: bool,
    keep_query_pages: bool,
    allow_external_pages: bool,
    include_external_assets: bool = True,
) -> pathlib.Path:
    start_url = canonicalize_url(start_url, keep_query=keep_query_pages)
    parsed_start = urlparse(start_url)

    if not is_http(start_url):
        raise ValueError("Start URL must be HTTP/HTTPS.")

    root_host = normalize_netloc(parsed_start)
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    queue = collections.deque([start_url])
    queued: set[str] = {start_url}
    seen_pages: set[str] = set()
    downloaded_assets: set[str] = set()

    sitemap_urls = discover_sitemaps(start_url, session, timeout)
    seeded_pages = collect_urls_from_sitemaps(
        sitemap_urls=sitemap_urls,
        session=session,
        timeout=timeout,
        root_host=root_host,
        include_related_hosts=include_related_hosts,
        allow_external_pages=allow_external_pages,
    )

    for page in sorted(seeded_pages):
        if page not in queued:
            queue.append(page)
            queued.add(page)

    while queue and len(seen_pages) < max_pages:
        url = queue.popleft()
        url = canonicalize_url(url, keep_query=keep_query_pages)

        if not url or url in seen_pages:
            continue

        if not is_http(url) or not in_scope(url, root_host, include_related_hosts, allow_external_pages):
            continue

        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            log(f"[WARN] Failed page {url}: {exc}")
            continue

        if is_cloudflare_challenge(resp):
            log(f"[WARN] Cloudflare challenge detected at {url}. Automated crawling is blocked for this host.")
            seen_pages.add(url)
            continue

        ct = resp.headers.get("Content-Type", "")
        if "text/html" not in ct:
            if url not in downloaded_assets:
                path = to_local_path(url, output_dir)
                save_content(resp, path)
                downloaded_assets.add(url)
                log(f"[ASSET] {url} -> {path}")
            continue

        seen_pages.add(url)
        page_path = to_local_path(url, output_dir)
        save_content(resp, page_path)
        log(f"[PAGE] {url} -> {page_path}")

        soup = BeautifulSoup(resp.text, "html.parser")

        for link in extract_page_links(soup, url):
            link = canonicalize_url(link, keep_query=keep_query_pages)
            if (
                link
                and in_scope(link, root_host, include_related_hosts, allow_external_pages)
                and link not in seen_pages
                and link not in queued
            ):
                queue.append(link)
                queued.add(link)

        for asset_url in extract_asset_links(soup, url):
            asset_url = canonicalize_url(asset_url, keep_query=True)
            if not asset_url or asset_url in downloaded_assets or not is_http(asset_url):
                continue

            # Scope check: allow all assets if include_external_assets is True
            if not include_external_assets and not in_scope(asset_url, root_host, include_related_hosts, allow_external_pages):
                continue

            try:
                asset_resp = session.get(asset_url, timeout=timeout)
                asset_ct = asset_resp.headers.get("Content-Type", "")
                if "text/html" in asset_ct:
                    page_candidate = canonicalize_url(asset_url, keep_query=keep_query_pages)
                    if (
                        page_candidate
                        and page_candidate not in seen_pages
                        and page_candidate not in queued
                        and in_scope(page_candidate, root_host, include_related_hosts, allow_external_pages)
                    ):
                        queue.append(page_candidate)
                        queued.add(page_candidate)
                    continue

                asset_path = to_local_path(asset_url, output_dir)
                save_content(asset_resp, asset_path)
                downloaded_assets.add(asset_url)
                log(f"[ASSET] {asset_url} -> {asset_path}")
            except requests.RequestException as exc:
                log(f"[WARN] Failed asset {asset_url}: {exc}")

        if delay > 0:
            time.sleep(delay)

    log("\nCrawl complete.")
    log(f"Pages downloaded: {len(seen_pages)}")
    log(f"Assets downloaded: {len(downloaded_assets)}")
    target_dir = output_dir / root_host if (output_dir / root_host).exists() else output_dir
    neutralize_webflow_branding(target_dir)
    log(f"Saved to: {target_dir.resolve()}")
    return target_dir


def neutralize_webflow_branding(target_dir: pathlib.Path) -> None:
    """Neutralizes Webflow badge/branding injection in all JS and CSS files."""
    brand_pattern = re.compile(
        r'a\.define\(\s*["\']brand["\']\s*,\s*e\.exports\s*=\s*function\s*\([^\)]*\)\s*\{[\s\S]*?\}\s*\)\s*\}'
    )
    badge_css = "\n\n/* Suppress Webflow brand badge */\n.w-webflow-badge { display: none !important; opacity: 0 !important; visibility: hidden !important; pointer-events: none !important; }\n"

    for js_file in target_dir.rglob("*.js"):
        try:
            content = js_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        modified = False
        if brand_pattern.search(content):
            content = brand_pattern.sub(
                'a.define("brand",e.exports=function(){return{ready:function(){try{var b=document.querySelector(".w-webflow-badge");if(b)b.remove();}catch(e){}}}})})}',
                content,
                count=1,
            )
            modified = True
        if "utm_campaign=brandjs" in content:
            content = content.replace("utm_campaign=brandjs", "utm_campaign=disabled")
            modified = True
        if modified:
            try:
                js_file.write_text(content, encoding="utf-8")
                log(f"[BRAND] Disarmed Webflow badge in: {js_file.name}")
            except OSError:
                pass

    for css_file in target_dir.rglob("*.css"):
        try:
            css_content = css_file.read_text(encoding="utf-8", errors="ignore")
            if ".w-webflow-badge" not in css_content:
                css_file.write_text(css_content + badge_css, encoding="utf-8")
        except OSError:
            pass


# ============================================================================
# React App Generator & HTML-to-JSX Converter
# ============================================================================

class ReactConverter:
    """Converts a directory of HTML and assets into a modern Vite + React SPA."""

    def __init__(self, source_dir: pathlib.Path, react_dir: pathlib.Path, session: requests.Session | None = None):
        self.source_dir = source_dir.resolve()
        self.react_dir = react_dir.resolve()
        self.public_dir = self.react_dir / "public"
        self.assets_dir = self.public_dir / "assets"
        self.src_dir = self.react_dir / "src"
        self.pages_dir = self.src_dir / "pages"
        self.hooks_dir = self.src_dir / "hooks"
        self.styles_dir = self.src_dir / "styles"
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        self.url_mapping: dict[str, str] = {}
        self.site_id: str = ""

    def run(self) -> None:
        log(f"\n[REACT] Converting site from: {self.source_dir}")
        log(f"[REACT] Destination React project: {self.react_dir}")

        self._create_directories()
        html_files = self._collect_html_files()
        if not html_files:
            log(f"[ERROR] No HTML files found in {self.source_dir}")
            return

        # Detect Webflow site ID from HTML files
        for f in html_files:
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r'data-wf-site=["\']([^"\']+)["\']', txt)
                if m:
                    self.site_id = m.group(1)
                    log(f"[REACT] Detected Webflow site ID: {self.site_id}")
                    break
            except OSError:
                continue

        log(f"[REACT] Found {len(html_files)} HTML pages.")
        self._localize_all_assets(html_files)
        neutralize_webflow_branding(self.assets_dir)
        self._extract_interaction_styles(html_files)
        self._generate_hook()
        converted_routes = self._convert_pages(html_files)
        self._generate_app(converted_routes)
        self._generate_index_html(html_files[0])
        self._generate_package_json()
        self._generate_vite_config()
        self._generate_main_jsx()

        log(f"\n[SUCCESS] Successfully generated React app at: {self.react_dir}")
        log("[SUCCESS] All routes, interactions, code splitting, and local assets are configured.")

    def _create_directories(self) -> None:
        for d in [
            self.assets_dir / "images",
            self.assets_dir / "css",
            self.assets_dir / "js",
            self.pages_dir,
            self.hooks_dir,
            self.styles_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    def _collect_html_files(self) -> list[pathlib.Path]:
        return sorted(list(self.source_dir.rglob("*.html")))

    def _localize_all_assets(self, html_files: list[pathlib.Path]) -> None:
        """Finds all remote URLs (CDN, fonts, JS) across all HTML files and downloads them."""
        log("[REACT] Scanning HTML files for external CDN assets...")
        url_set: set[str] = set()

        cdn_regex = re.compile(r'https?://[A-Za-z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+\.[a-zA-Z0-9]+(?:\?[^\s"\'><)]*)?', re.I)

        for file_path in html_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for match in cdn_regex.finditer(content):
                u = match.group(0).rstrip(r",;)}]'\"")
                if any(ext in u.lower() for ext in [
                    ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".avif", ".ico",
                    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".webm"
                ]):
                    url_set.add(u)

            # Check for Google WebFont, jQuery, CloudFront, GSAP
            for script_match in re.finditer(r'<script[^>]+src=["\']([^"\']+)["\']', content, re.I):
                src = script_match.group(1).strip()
                if is_http(src):
                    url_set.add(src)

        log(f"[REACT] Discovered {len(url_set)} unique asset URLs.")

        # Download missing assets
        base_urls = [u for u in url_set if not re.search(r'-p-\d+\.', u)]
        log(f"[REACT] Downloading {len(base_urls)} base assets in parallel...")

        downloaded, skipped, failed = 0, 0, 0

        def download_single(u: str) -> tuple[str, bool]:
            parsed = urlparse(u)
            filename = posixpath.basename(parsed.path) or "asset"
            filename = unquote(filename)
            filename = re.sub(r'[<>:"/\\|?*]', '_', filename).replace(' ', '_')

            if u.endswith(".css") or "/css" in parsed.path:
                dest = self.assets_dir / "css" / filename
                web_path = f"/assets/css/{filename}"
            elif u.endswith(".js") or "/js" in parsed.path:
                dest = self.assets_dir / "js" / filename
                web_path = f"/assets/js/{filename}"
            else:
                dest = self.assets_dir / "images" / filename
                web_path = f"/assets/images/{filename}"

            self.url_mapping[u] = web_path

            if dest.exists() and dest.stat().st_size > 0:
                return u, True

            try:
                resp = self.session.get(u, timeout=15)
                if resp.status_code == 200:
                    dest.write_bytes(resp.content)
                    return u, True
                return u, False
            except requests.RequestException:
                return u, False

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = executor.map(download_single, base_urls)
            for u, ok in results:
                if ok:
                    downloaded += 1
                else:
                    failed += 1

        # Map responsive variants (-p-500, -p-800) to base image
        for u in url_set:
            if u not in self.url_mapping:
                base_u = re.sub(r'-p-\d+(\.[a-zA-Z0-9]+)$', r'\1', u)
                if base_u in self.url_mapping:
                    self.url_mapping[u] = self.url_mapping[base_u]
                else:
                    download_single(u)

        mapping_file = self.public_dir / "url-mapping.json"
        mapping_file.write_text(json.dumps(self.url_mapping, indent=2), encoding="utf-8")
        log(f"[REACT] Asset localization complete: {downloaded} downloaded/cached, {failed} failed.")
        log(f"[REACT] URL mapping saved to {mapping_file}")

    def _extract_interaction_styles(self, html_files: list[pathlib.Path]) -> None:
        """Extracts CSS animation/interaction initial state rules into page-interactions.css."""
        unique_styles: set[str] = set()
        unique_styles.add(
            "/* Suppress Webflow badge */\n"
            ".w-webflow-badge {\n"
            "  display: none !important;\n"
            "  opacity: 0 !important;\n"
            "  visibility: hidden !important;\n"
            "  pointer-events: none !important;\n"
            "}"
        )
        for f in html_files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in re.finditer(r'<style\b[^>]*>([\s\S]*?)</style>', content, re.I):
                s = match.group(1).strip()
                if "w-mod-js" in s or "data-w-id" in s:
                    unique_styles.add(s)

        css_path = self.styles_dir / "page-interactions.css"
        css_path.write_text("\n\n".join(unique_styles), encoding="utf-8")
        log(f"[REACT] Extracted {len(unique_styles)} interaction style blocks to {css_path}")

    def _generate_hook(self) -> None:
        site_attr = f"    document.documentElement.setAttribute('data-wf-site', '{self.site_id}');\n" if self.site_id else ""
        hook_code = f"""import {{ useEffect }} from 'react';

export default function useWebflow(pageId) {{
  useEffect(() => {{
    if (pageId) {{
      document.documentElement.setAttribute('data-wf-page', pageId);
    }}
{site_attr}
    if (!document.documentElement.classList.contains('w-mod-js')) {{
      document.documentElement.classList.add('w-mod-js');
    }}

    window.scrollTo(0, 0);

    const timer = setTimeout(() => {{
      if (window.Webflow) {{
        try {{
          if (window.Webflow.destroy) {{
            window.Webflow.destroy();
          }}
          if (window.Webflow.ready) {{
            window.Webflow.ready();
          }}
          const ix2 = window.Webflow.require && window.Webflow.require('ix2');
          if (ix2 && ix2.init) {{
            ix2.init();
          }}
        }} catch (e) {{
          console.warn('Webflow reinit warning:', e);
        }}
      }}
    }}, 50);

    return () => {{
      clearTimeout(timer);
      if (window.Webflow && window.Webflow.destroy) {{
        try {{
          window.Webflow.destroy();
        }} catch (e) {{}}
      }}
    }};
  }}, [pageId]);
}}
"""
        (self.hooks_dir / "useWebflow.js").write_text(hook_code, encoding="utf-8")

    def _style_str_to_jsx(self, style_str: str) -> str:
        styles = {}
        for rule in style_str.split(";"):
            if not rule.strip() or ":" not in rule:
                continue
            prop, val = rule.split(":", 1)
            prop = prop.strip()
            val = val.strip()
            if not prop or not val:
                continue

            if prop.startswith("-webkit-"):
                camel = "Webkit" + "".join(part.capitalize() for part in prop[8:].split("-"))
            elif prop.startswith("-moz-"):
                camel = "Moz" + "".join(part.capitalize() for part in prop[5:].split("-"))
            elif prop.startswith("-ms-"):
                camel = "ms" + "".join(part.capitalize() for part in prop[4:].split("-"))
            else:
                parts = prop.split("-")
                camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
            styles[camel] = val
        return json.dumps(styles)

    def _html_to_jsx(self, html: str) -> str:
        # 1. Remove comments
        jsx = re.sub(r'<!--[\s\S]*?-->', '', html)

        # 2. Embedded <style> inside body
        def replace_style(m: re.Match) -> str:
            attrs = m.group(1)
            content = json.dumps(m.group(2).strip())
            return f'<style{attrs} dangerouslySetInnerHTML={{{{ __html: {content} }}}}></style>'

        jsx = re.sub(r'<style\b([^>]*)>([\s\S]*?)</style>', replace_style, jsx, flags=re.I)

        # 3. JSON scripts (lightboxes, data nodes)
        def replace_json_script(m: re.Match) -> str:
            attrs = m.group(1)
            content = m.group(2)
            for remote_url, local_path in self.url_mapping.items():
                content = content.replace(remote_url, local_path)
            escaped = json.dumps(content.strip())
            attrs_jsx = re.sub(r'\bclass="', 'className="', attrs)
            return f'<script{attrs_jsx} dangerouslySetInnerHTML={{{{ __html: {escaped} }}}}></script>'

        jsx = re.sub(r'<script([^>]*type=["\']application/json["\'][^>]*)>([\s\S]*?)</script>', replace_json_script, jsx, flags=re.I)

        # 4. Templates
        def replace_template(m: re.Match) -> str:
            attrs = m.group(1)
            content = m.group(2)
            for remote_url, local_path in self.url_mapping.items():
                content = content.replace(remote_url, local_path)
            escaped = json.dumps(content)
            attrs_jsx = re.sub(r'\bclass="', 'className="', attrs)
            return f'<script{attrs_jsx} dangerouslySetInnerHTML={{{{ __html: {escaped} }}}}></script>'

        jsx = re.sub(r'<script([^>]*type=["\']text/x-wf-template["\'][^>]*)>([\s\S]*?)</script>', replace_template, jsx, flags=re.I)

        # 5. Replace mapped URLs
        for remote_url, local_path in self.url_mapping.items():
            jsx = jsx.replace(remote_url, local_path)
            encoded = urllib.parse.quote(remote_url, safe="/:?=&%")
            if encoded != remote_url:
                jsx = jsx.replace(encoded, local_path)

        # Replace any residual CDN URL format
        jsx = re.sub(r'https?://cdn\.prod\.website-files\.com/[^\s"\'><)]+', lambda m: f"/assets/images/{posixpath.basename(m.group(0))}", jsx)

        # Replace live domain with relative routes
        jsx = re.sub(r'https?://[a-zA-Z0-9\-.]+\.webflow\.io/', '/', jsx)

        # 6. Attributes conversion
        jsx = re.sub(r'\bclass="([^"]*)"', r'className="\1"', jsx)
        jsx = re.sub(r'\bfor="([^"]*)"', r'htmlFor="\1"', jsx)
        jsx = re.sub(r'\btabindex="([^"]*)"', r'tabIndex="\1"', jsx, flags=re.I)
        jsx = re.sub(r'\bautocomplete="([^"]*)"', r'autoComplete="\1"', jsx, flags=re.I)
        jsx = re.sub(r'\bautofocus\b', 'autoFocus', jsx, flags=re.I)
        jsx = re.sub(r'\binputmode="([^"]*)"', r'inputMode="\1"', jsx, flags=re.I)

        # Input value -> defaultValue
        jsx = re.sub(r'<input\b(?![^>]*\btype=["\'](?:button|submit)["\'])([^>]*?)\bvalue="([^"]*)"([^>]*?)>', r'<input\1defaultValue="\2"\3>', jsx, flags=re.I)

        # SVG attributes
        svg_attrs = [
            ("stroke-width", "strokeWidth"),
            ("stroke-linecap", "strokeLinecap"),
            ("stroke-linejoin", "strokeLinejoin"),
            ("clip-rule", "clipRule"),
            ("fill-rule", "fillRule"),
            ("xmlns:xlink", "xmlnsXlink"),
            ("xlink:href", "xlinkHref"),
            ("stop-color", "stopColor"),
            ("stop-opacity", "stopOpacity"),
            ("font-family", "fontFamily"),
            ("font-size", "fontSize"),
        ]
        for src, dest in svg_attrs:
            jsx = re.sub(rf'\b{src}="([^"]*)"', rf'{dest}="\1"', jsx, flags=re.I)

        # Style attribute to JSX style object
        def replace_inline_style(m: re.Match) -> str:
            style_content = m.group(1)
            style_obj = self._style_str_to_jsx(style_content)
            return f"style={{{style_obj}}}"

        jsx = re.sub(r'\bstyle="([^"]*)"', replace_inline_style, jsx)

        # Self-closing void tags
        jsx = re.sub(r'<(img|input|br|hr)([^>]*?)(?<!/)>', r'<\1\2 />', jsx, flags=re.I)

        return jsx

    def _convert_pages(self, html_files: list[pathlib.Path]) -> list[dict]:
        routes = []

        for f in html_files:
            rel = f.relative_to(self.source_dir).as_posix()
            try:
                html_text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            # Route
            route = "/" + re.sub(r'(?:^|/)(?:index)?\.html$', '', rel).lstrip("/")
            if not route:
                route = "/"

            page_id_match = re.search(r'data-wf-page="([^"]+)"', html_text)
            page_id = page_id_match.group(1) if page_id_match else ""

            body_match = re.search(r'<body[^>]*>([\s\S]*?)</body>', html_text, re.I)
            if not body_match:
                continue
            body_html = body_match.group(1)

            # Strip external bottom scripts
            body_html = re.sub(r'<script[^>]*src=[\s\S]*?</script>', '', body_html, flags=re.I)
            # Strip non-template/non-json inline scripts
            body_html = re.sub(r'<script(?![^>]*type=["\'](?:text/x-wf-template|application/json)["\'])[\s\S]*?</script>', '', body_html, flags=re.I)

            converted_jsx = self._html_to_jsx(body_html)

            # Component Name
            clean_rel = re.sub(r'(/index)?\.html$', '', rel)
            if not clean_rel or clean_rel == "index":
                comp_name = "Home"
            else:
                parts = [re.sub(r'[^a-zA-Z0-9]', '', p.title()) for p in clean_rel.split("/")]
                comp_name = "_".join(parts)
            if comp_name[0].isdigit():
                comp_name = "Page" + comp_name

            if rel == "index.html":
                out_rel = "Home.jsx"
            else:
                out_rel = re.sub(r'(/index)?\.html$', '.jsx', rel)

            out_file = self.pages_dir / out_rel
            out_file.parent.mkdir(parents=True, exist_ok=True)

            # Calculate relative path to hook
            depth = len(out_rel.split("/")) - 1
            hook_rel = "../" * (depth + 1) + "hooks/useWebflow"

            # Check for custom scripts (e.g. GSAP marquee in career)
            extra_imports = ""
            extra_hooks = ""
            if "showcase-marquee-list" in html_text and "gsap" in html_text:
                extra_imports = ", { useEffect }"
                extra_hooks = """
  useEffect(() => {
    if (typeof window.gsap === 'undefined' || typeof window.Observer === 'undefined') return;
    const gsap = window.gsap;
    const Observer = window.Observer;
    const $ = window.$;

    let object = { value: 1 };
    let tl = gsap.timeline({
      repeat: -1,
      onReverseComplete: () => { tl.progress(1); },
    });

    tl.fromTo(
      '.showcase-marquee-list',
      { xPercent: 0 },
      { xPercent: -100, duration: 20, ease: 'none' }
    );

    const obs = Observer.create({
      target: window,
      type: 'wheel,scroll,touch',
      onChangeY: (self) => {
        let v = self.velocityY * 0.002;
        v = gsap.utils.clamp(-40, 40, v);
        tl.timeScale(v);
        let resting = v < 0 ? -1 : 1;
        gsap.fromTo(
          object,
          { value: v },
          {
            value: resting,
            duration: 1,
            onUpdate: () => { tl.timeScale(object.value); },
          }
        );
      },
    });

    return () => {
      tl.kill();
      obs.kill();
    };
  }, []);
"""

            code = f"""import React{extra_imports} from 'react';
import useWebflow from '{hook_rel}';

export default function {comp_name}() {{
  useWebflow('{page_id}');{extra_hooks}

  return (
    <>
      {converted_jsx}
    </>
  );
}}
"""
            out_file.write_text(code, encoding="utf-8")
            routes.append({
                "route": route,
                "name": comp_name,
                "import_path": "./pages/" + out_rel.replace(".jsx", ""),
            })

        return routes

    def _generate_app(self, routes: list[dict]) -> None:
        if not routes:
            return

        # Ensure root route exists
        active_routes = list(routes)
        if not any(r["route"] == "/" for r in active_routes):
            active_routes.insert(0, {
                "route": "/",
                "name": active_routes[0]["name"],
                "import_path": active_routes[0]["import_path"],
            })

        lazy_imports = "\n".join(
            [f"const {r['name']} = lazy(() => import('{r['import_path']}'));" for r in active_routes]
        )
        route_elements = "\n".join(
            [f'          <Route path="{r["route"]}" element={{<{r["name"]} />}} />' for r in active_routes]
        )

        has_404 = next((r for r in active_routes if "404" in r["route"]), None)
        fallback_comp = has_404["name"] if has_404 else active_routes[0]["name"]
        route_elements += f'\n          <Route path="*" element={{<{fallback_comp} />}} />'

        app_code = f"""import React, {{ useEffect, Suspense, lazy }} from 'react';
import {{ Routes, Route, useNavigate, useLocation }} from 'react-router-dom';

{lazy_imports}

export default function App() {{
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {{
    const handleClick = (e) => {{
      const anchor = e.target.closest('a');
      if (!anchor) return;
      const href = anchor.getAttribute('href');
      if (!href) return;

      if (href.startsWith('/') && !href.startsWith('//') && !href.startsWith('/assets') && !href.includes('#')) {{
        e.preventDefault();
        navigate(href);
      }}
    }};

    document.addEventListener('click', handleClick);
    return () => document.removeEventListener('click', handleClick);
  }}, [navigate]);

  return (
    <Suspense fallback={{<div style={{{{ minHeight: '100vh', background: '#0a0a0a' }}}}></div>}}>
      <Routes>
{route_elements}
      </Routes>
    </Suspense>
  );
}}
"""
        (self.src_dir / "App.jsx").write_text(app_code, encoding="utf-8")

    def _generate_index_html(self, sample_html: pathlib.Path) -> None:
        html_text = sample_html.read_text(encoding="utf-8", errors="ignore")

        # Extract title
        title_m = re.search(r'<title>([^<]+)</title>', html_text, re.I)
        title = title_m.group(1).strip() if title_m else "React Webflow App"

        # Extract Google font links & preconnects
        font_tags = []
        for m in re.finditer(r'<link[^>]+(?:fonts\.googleapis\.com|fonts\.gstatic\.com)[^>]*>', html_text, re.I):
            font_tags.append(m.group(0))
        if not font_tags:
            font_tags = [
                '<link rel="preconnect" href="https://fonts.googleapis.com" />',
                '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />',
                '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />'
            ]

        # Extract WebFont script blocks if present
        webfont_scripts = []
        for m in re.finditer(r'<script[^>]*>(?:[\s\S]*?WebFont\.load[\s\S]*?)</script>', html_text, re.I):
            webfont_scripts.append(m.group(0))

        # Extract favicons
        favicon_tags = []
        for m in re.finditer(r'<link[^>]+rel=["\'](?:shortcut icon|icon|apple-touch-icon)["\'][^>]*>', html_text, re.I):
            tag = m.group(0)
            for remote_u, local_p in self.url_mapping.items():
                tag = tag.replace(remote_u, local_p)
            favicon_tags.append(tag)

        # Collect CSS and JS files in assets
        css_files = [f"/assets/css/{f.name}" for f in (self.assets_dir / "css").glob("*.css")]
        js_files = [f"/assets/js/{f.name}" for f in (self.assets_dir / "js").glob("*.js")]

        # Put critical runtime first
        ordered_js = []
        for name in ["jquery", "webfont", "webflow.schunk", "webflow", "gsap", "Observer"]:
            for j in js_files:
                if name in j.lower() and j not in ordered_js:
                    ordered_js.append(j)
        for j in js_files:
            if j not in ordered_js:
                ordered_js.append(j)

        css_tags = "\n    ".join([f'<link rel="stylesheet" href="{c}" />' for c in css_files])
        js_tags = "\n    ".join([f'<script src="{j}"></script>' for j in ordered_js])
        fonts_html = "\n    ".join(font_tags)
        favicons_html = "\n    ".join(favicon_tags)
        webfonts_html = "\n    ".join(webfont_scripts)

        index_html = f"""<!doctype html>
<html lang="en" class="w-mod-js">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    {fonts_html}
    {favicons_html}
    {css_tags}
    {webfonts_html}
    <script type="text/javascript">
      window.__WEBFLOW_CURRENCY_SETTINGS = {{"currencyCode":"USD","symbol":"$","decimal":".","fractionDigits":2,"group":",","template":"{{{{wf \\"path\\":\\"symbol\\",\\"type\\":\\"PlainText\\"}}}} {{{{wf \\"path\\":\\"amount\\",\\"type\\":\\"CommercePrice\\"}}}} {{{{wf \\"path\\":\\"currencyCode\\",\\"type\\":\\"PlainText\\"}}}}","hideDecimalForWholeNumbers":false}};
      !function(o,c){{var n=c.documentElement,t=" w-mod-";n.className+=t+"js",("ontouchstart"in o||o.DocumentTouch&&c instanceof DocumentTouch)&&(n.className+=t+"touch")}}(window,document);
    </script>
  </head>
  <body>
    <div id="root"></div>
    {js_tags}
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""
        (self.react_dir / "index.html").write_text(index_html, encoding="utf-8")

    def _generate_package_json(self) -> None:
        pkg = {
            "name": self.react_dir.name.lower().replace(" ", "-"),
            "private": True,
            "version": "1.0.0",
            "type": "module",
            "scripts": {
                "dev": "vite",
                "build": "vite build",
                "preview": "vite preview"
            },
            "dependencies": {
                "react": "^19.0.0",
                "react-dom": "^19.0.0",
                "react-router-dom": "^7.0.0",
                "framer-motion": "^12.0.0"
            },
            "devDependencies": {
                "@vitejs/plugin-react": "^4.3.0",
                "vite": "^6.0.0"
            }
        }
        (self.react_dir / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")

    def _generate_vite_config(self) -> None:
        vite_config = """import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
"""
        (self.react_dir / "vite.config.js").write_text(vite_config, encoding="utf-8")

    def _generate_main_jsx(self) -> None:
        main_code = """import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import './styles/page-interactions.css';
import App from './App.jsx';

createRoot(document.getElementById('root')).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>
);
"""
        (self.src_dir / "main.jsx").write_text(main_code, encoding="utf-8")


# ============================================================================
# CLI & Entry Point
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download websites with all assets (including CDNs) and automatically convert them into modern Vite + React apps."
    )
    parser.add_argument("url", nargs="?", default=None, help="Start URL to download, e.g. https://www.example.com")
    parser.add_argument("-o", "--output", default="downloaded_site", help="Output directory for downloaded site (default: downloaded_site)")
    parser.add_argument("--max-pages", type=int, default=2000, help="Maximum HTML pages to crawl (default: 2000)")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay between page requests in seconds (default: 0.1)")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds (default: 20)")
    parser.add_argument(
        "--include-related-hosts",
        action="store_true",
        help="Also crawl hosts under the same root domain.",
    )
    parser.add_argument(
        "--keep-query-pages",
        action="store_true",
        help="Treat query-string page URLs as unique pages.",
    )
    parser.add_argument(
        "--allow-external-pages",
        action="store_true",
        help="Allow crawling HTML pages on other external hosts discovered.",
    )
    parser.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        help="User-Agent string",
    )
    parser.add_argument(
        "--no-external-assets",
        action="store_false",
        dest="include_external_assets",
        default=True,
        help="Do not download external CDN assets (default is to download all CDN assets)",
    )
    parser.add_argument(
        "--to-react",
        nargs="?",
        const="",
        default=None,
        help="Convert downloaded site into a Vite + React app (optional path: --to-react [OUTPUT_DIR])",
    )
    parser.add_argument(
        "--convert-dir",
        default=None,
        help="Convert an existing directory of HTML/assets to a React app without downloading",
    )
    parser.add_argument(
        "--react-out",
        default=None,
        help="Output directory when using --convert-dir",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Mode 1: Convert an existing directory directly
    if args.convert_dir:
        src = pathlib.Path(args.convert_dir)
        dest = pathlib.Path(args.react_out) if args.react_out else src.parent / f"{src.name}-react"
        converter = ReactConverter(source_dir=src, react_dir=dest)
        converter.run()
        return

    # Mode 2: Download site
    if not args.url:
        log("[ERROR] Please provide a URL to download or use --convert-dir.")
        return

    out_dir = pathlib.Path(args.output)
    downloaded_path = download_site(
        start_url=args.url,
        output_dir=out_dir,
        max_pages=args.max_pages,
        delay=args.delay,
        timeout=args.timeout,
        user_agent=args.user_agent,
        include_related_hosts=args.include_related_hosts,
        keep_query_pages=args.keep_query_pages,
        allow_external_pages=args.allow_external_pages,
        include_external_assets=args.include_external_assets,
    )

    # Optional automatic conversion to React
    if args.to_react is not None:
        react_dest = pathlib.Path(args.to_react) if args.to_react else out_dir.parent / f"{out_dir.name}-react"
        converter = ReactConverter(source_dir=downloaded_path, react_dir=react_dest)
        converter.run()


if __name__ == "__main__":
    main()
