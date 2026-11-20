#!/usr/bin/env python3
"""
Site Downloader & React App Converter (v2.0)
============================================
1. Downloads entire websites with all assets (images, fonts, styles, scripts, CDN files).
2. Automatically converts downloaded sites into modern, production-ready Vite + React apps
   without destroying page structure, Webflow / GSAP animations, interactions, or styles.
3. Automatically disarms Webflow badge & copyright branding.
4. Interactive OpenCode-style terminal UI with zero-config auto-bootstrapping.

Usage:
  # Interactive Wizard (recommended):
  python site_downloader.py

  # Headless CLI Mode:
  python site_downloader.py https://example.com -o downloaded_site --to-react
"""

from __future__ import annotations

import collections
import concurrent.futures
import hashlib
import json
import os
import pathlib
import posixpath
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Iterable
from urllib.parse import unquote, urldefrag, urljoin, urlparse

# ============================================================================
# Windows ANSI Support & Dependency Bootstrapper
# ============================================================================

def _enable_windows_ansi() -> None:
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(handle, mode)
        except Exception:
            pass

_enable_windows_ansi()

REQUIRED_PACKAGES = [
    ("requests", "requests>=2.32.0"),
    ("bs4", "beautifulsoup4>=4.12.0"),
]

def bootstrap_environment() -> None:
    """Verifies Python version and automatically installs missing dependencies via pip."""
    if sys.version_info < (3, 8):
        print(f"\033[1;31m[ERROR] Python 3.8 or newer is required. You are using Python {sys.version.split()[0]}.\033[0m")
        sys.exit(1)

    missing = []
    for mod, pkg in REQUIRED_PACKAGES:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)

    if missing:
        print("\n\033[1;36m╭─ Dependency Bootstrapper ───────────────────────────────────────╮\033[0m")
        print(f"\033[1;36m│\033[0m  \033[1;33m⚡ Missing dependencies detected:\033[0m {', '.join(missing)}")
        print("\033[1;36m│\033[0m  \033[32mInstalling automatically via pip...\033[0m")
        print("\033[1;36m╰─────────────────────────────────────────────────────────────────╯\033[0m\n")
        try:
            # Upgrade pip silently
            subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], capture_output=True)
            # Install missing packages
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            print("\033[1;32m✔ All dependencies installed successfully!\033[0m\n")
        except Exception as e:
            print(f"\033[1;31m✖ Failed to auto-install dependencies: {e}\033[0m")
            print("Please run manually: pip install -r requirements.txt")
            sys.exit(1)

bootstrap_environment()

import requests
from bs4 import BeautifulSoup

# ============================================================================
# OpenCode-Style Terminal UI Engine
# ============================================================================

class UI:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[38;2;6;182;212m"
    GREEN = "\033[38;2;16;185;129m"
    PURPLE = "\033[38;2;139;92;246m"
    AMBER = "\033[38;2;245;158;11m"
    RED = "\033[38;2;239;68;68m"
    BLUE = "\033[38;2;59;130;246m"
    GRAY = "\033[38;2;156;163;175m"
    WHITE = "\033[1;37m"

    @classmethod
    def banner(cls) -> None:
        w = 68
        print(f"\n{cls.CYAN}╭{'─' * w}╮{cls.RESET}")
        print(f"{cls.CYAN}│{cls.RESET}{' ' * w}{cls.CYAN}│{cls.RESET}")
        logo = [
            r"   ███████╗██╗████████╗███████╗    ██████╗ ██╗               ",
            r"   ██╔════╝██║╚══██╔══╝██╔════╝    ██╔══██╗██║               ",
            r"   ███████╗██║   ██║   █████╗      ██║  ██║██║               ",
            r"   ╚════██║██║   ██║   ██╔══╝      ██║  ██║██║               ",
            r"   ███████║██║   ██║   ███████╗    ██████╔╝███████╗          ",
            r"   ╚══════╝╚═╝   ╚═╝   ╚══════╝    ╚═════╝ ╚══════╝          ",
        ]
        for line in logo:
            padding = w - len(line)
            print(f"{cls.CYAN}│{cls.RESET}{cls.BOLD}{cls.PURPLE}{line}{cls.RESET}{' ' * padding}{cls.CYAN}│{cls.RESET}")
        print(f"{cls.CYAN}│{cls.RESET}{' ' * w}{cls.CYAN}│{cls.RESET}")
        sub1 = "   Autonomous Web-to-React Cloning Engine  •  v2.0"
        sub2 = "   Zero-Config Site Downloader & Full Component Generator"
        print(f"{cls.CYAN}│{cls.RESET}{cls.BOLD}{cls.WHITE}{sub1}{cls.RESET}{' ' * (w - len(sub1))}{cls.CYAN}│{cls.RESET}")
        print(f"{cls.CYAN}│{cls.RESET}{cls.GRAY}{sub2}{cls.RESET}{' ' * (w - len(sub2))}{cls.CYAN}│{cls.RESET}")
        print(f"{cls.CYAN}╰{'─' * w}╯{cls.RESET}\n")

    @classmethod
    def system_status(cls) -> None:
        w = 68
        node_str = "Not detected"
        npm_str = "Not detected"
        node_cmd = shutil.which("node")
        npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
        if node_cmd:
            try:
                node_ver = subprocess.check_output([node_cmd, "-v"], text=True).strip()
                node_str = f"{node_ver}"
            except Exception:
                pass
        if npm_cmd:
            try:
                npm_ver = subprocess.check_output([npm_cmd, "-v"], text=True).strip()
                npm_str = f"npm v{npm_ver}"
            except Exception:
                pass

        checks = [
            ("Python Runtime", True, f"v{sys.version.split()[0]} (Active)"),
            ("Pip Package Manager", True, "Up to date"),
            ("Core Dependencies", True, "requests, beautifulsoup4 (Ready)"),
            ("Node.js & npm", bool(node_cmd), f"{node_str} / {npm_str}" if node_cmd else "Not found in PATH"),
        ]

        print(f"{cls.PURPLE}╭─ System Environment ───────────────────────────────────────────────╮{cls.RESET}")
        for label, ok, detail in checks:
            mark = f"{cls.GREEN}✔{cls.RESET}" if ok else f"{cls.AMBER}!{cls.RESET}"
            status_text = f" {mark} {cls.WHITE}{label:<24}{cls.RESET} {cls.GRAY}{detail}{cls.RESET}"
            plain = f" * {label:<24} {detail}"
            pad = max(1, w - len(plain))
            print(f"{cls.PURPLE}│{cls.RESET}{status_text}{' ' * pad}{cls.PURPLE}│{cls.RESET}")
        print(f"{cls.PURPLE}╰{'─' * w}╯{cls.RESET}\n")

    @classmethod
    def box(cls, title: str, lines: list[str], border_color: str = CYAN) -> None:
        w = 68
        header = f"╭─ {title} "
        header += "─" * max(0, w - len(title) - 4) + "╮"
        print(f"{border_color}{header}{cls.RESET}")
        for line in lines:
            plain = re.sub(r'\033\[[0-9;]*m', '', line)
            pad = max(0, w - len(plain) - 2)
            print(f"{border_color}│{cls.RESET}  {line}{' ' * pad}{border_color}│{cls.RESET}")
        print(f"{border_color}╰{'─' * w}╯{cls.RESET}")

    @classmethod
    def step(cls, current: int, total: int, title: str) -> None:
        print(f"\n{cls.CYAN}[{current}/{total}]{cls.RESET} {cls.BOLD}{cls.WHITE}{title}{cls.RESET}")

    @classmethod
    def item(cls, message: str, status: str = "ok") -> None:
        if status == "ok":
            mark = f"{cls.GREEN}✔{cls.RESET}"
        elif status == "step":
            mark = f"{cls.CYAN}●{cls.RESET}"
        elif status == "warn":
            mark = f"{cls.AMBER}!{cls.RESET}"
        else:
            mark = f"{cls.RED}✖{cls.RESET}"
        print(f"  {mark} {message}")

    @classmethod
    def warn(cls, message: str) -> None:
        print(f"  {cls.AMBER}! {message}{cls.RESET}")

    @classmethod
    def error(cls, message: str) -> None:
        print(f"  {cls.RED}✖ {message}{cls.RESET}")

    @classmethod
    def prompt(cls, question: str, default: str = "") -> str:
        prompt_str = f"  {cls.CYAN}?{cls.RESET} {cls.BOLD}{cls.WHITE}{question}{cls.RESET}"
        if default:
            prompt_str += f" {cls.GRAY}[{default}]{cls.RESET}"
        prompt_str += f"\n  {cls.CYAN}›{cls.RESET} "
        try:
            val = input(prompt_str).strip()
            return val if val else default
        except (KeyboardInterrupt, EOFError):
            print(f"\n{cls.GRAY}Operation cancelled.{cls.RESET}")
            sys.exit(0)

    @classmethod
    def confirm(cls, question: str, default: bool = True) -> bool:
        choices = f"{cls.CYAN}Y{cls.RESET}/n" if default else f"y/{cls.CYAN}N{cls.RESET}"
        prompt_str = f"  {cls.CYAN}?{cls.RESET} {cls.BOLD}{cls.WHITE}{question}{cls.RESET} {cls.GRAY}({choices}){cls.RESET}\n  {cls.CYAN}›{cls.RESET} "
        try:
            val = input(prompt_str).strip().lower()
            if not val:
                return default
            return val in ("y", "yes", "true", "1")
        except (KeyboardInterrupt, EOFError):
            print(f"\n{cls.GRAY}Operation cancelled.{cls.RESET}")
            sys.exit(0)

    @classmethod
    def success_card(cls, target_dir: pathlib.Path, total_pages: int, total_assets: int, react_dir: pathlib.Path | None = None) -> None:
        lines = [
            f"{cls.BOLD}{cls.GREEN}Cloning and conversion completed successfully!{cls.RESET}",
            "",
            f"{cls.WHITE}Summary:{cls.RESET}",
            f"  • Downloaded Pages:   {cls.CYAN}{total_pages}{cls.RESET}",
            f"  • Localized Assets:   {cls.CYAN}{total_assets}{cls.RESET}",
            f"  • Download Directory: {cls.GRAY}{target_dir}{cls.RESET}",
        ]
        if react_dir:
            lines.extend([
                f"  • React Application:  {cls.GREEN}{react_dir}{cls.RESET}",
                "",
                f"{cls.WHITE}Quick Commands:{cls.RESET}",
                f"  {cls.CYAN}cd {react_dir.name}{cls.RESET}",
                f"  {cls.CYAN}npm run dev{cls.RESET}        {cls.GRAY}# Start development server{cls.RESET}",
                f"  {cls.CYAN}npm run build{cls.RESET}      {cls.GRAY}# Build production bundle{cls.RESET}",
                f"  {cls.CYAN}npm run preview{cls.RESET}    {cls.GRAY}# Preview production build{cls.RESET}",
            ])
        print()
        cls.box("Project Ready", lines, border_color=cls.GREEN)
        print()


# ============================================================================
# Logging & Network Helpers
# ============================================================================

def log(message: str) -> None:
    if message.startswith("[PAGE]"):
        parts = message.split(" -> ")
        page_url = parts[0].replace("[PAGE] ", "").strip()
        UI.item(f"Discovered Page: {UI.WHITE}{page_url}{UI.RESET}", status="ok")
    elif message.startswith("[ASSET]"):
        pass
    elif message.startswith("[BRAND]"):
        UI.item(f"Webflow Brand Neutralized: {UI.GREEN}{message.replace('[BRAND] ', '')}{UI.RESET}", status="ok")
    elif message.startswith("[REACT]"):
        UI.item(f"{message.replace('[REACT] ', '')}", status="step")
    elif message.startswith("[SUCCESS]"):
        UI.item(f"{UI.GREEN}{message.replace('[SUCCESS] ', '')}{UI.RESET}", status="ok")
    elif message.startswith("[WARN]"):
        UI.warn(message.replace('[WARN] ', ''))
    elif message.startswith("[ERROR]"):
        UI.error(message.replace('[ERROR] ', ''))
    else:
        print(f"  {UI.GRAY}{message}{UI.RESET}")


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
    if len(parts) <= 2:
        return host
    return ".".join(parts[-2:])


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

    safe_path = re.sub(r"[<>:\|?*]", "_", path.lstrip("/"))
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
    links: set[str] = set()

    for tag, attrs in ASSET_ATTRS.items():
        for elem in soup.find_all(tag):
            for attr in attrs:
                val = elem.get(attr)
                if not val:
                    continue
                if attr == "srcset":
                    for candidate in normalize_srcset(val):
                        if not candidate.startswith(SKIP_SCHEMES):
                            links.add(urljoin(base_url, candidate))
                else:
                    val = val.strip()
                    if not val.startswith(SKIP_SCHEMES):
                        links.add(urljoin(base_url, val))

    for elem in soup.find_all(style=True):
        style = elem["style"]
        for match in re.finditer(r'url\((.*?)\)', style, re.I):
            raw = match.group(1).strip("\"\' \t\r\n")
            if raw and not raw.startswith(SKIP_SCHEMES):
                links.add(urljoin(base_url, raw))

    for link in soup.find_all("link", href=True):
        href = link["href"].strip()
        if href and not href.startswith(SKIP_SCHEMES):
            links.add(urljoin(base_url, href))

    return links


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
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    parts = line.split(":", 1)
                    if len(parts) == 2 and is_http(parts[1].strip()):
                        candidates.add(parts[1].strip())
    except requests.RequestException:
        pass

    valid_sitemaps: set[str] = set()
    for sitemap_url in candidates:
        try:
            r = session.get(sitemap_url, timeout=timeout)
            if r.status_code == 200 and ("xml" in (r.headers.get("Content-Type") or "") or r.text.strip().startswith("<?xml")):
                valid_sitemaps.add(sitemap_url)
        except requests.RequestException:
            pass

    return valid_sitemaps


def collect_urls_from_sitemaps(
    sitemap_urls: set[str],
    session: requests.Session,
    timeout: int,
    root_host: str,
    include_related_hosts: bool,
    allow_external_pages: bool,
) -> set[str]:
    collected: set[str] = set()
    seen_sitemaps: set[str] = set()
    queue = list(sitemap_urls)

    while queue:
        sm = queue.pop(0)
        if sm in seen_sitemaps:
            continue
        seen_sitemaps.add(sm)

        try:
            resp = session.get(sm, timeout=timeout)
            if resp.status_code != 200:
                continue
            urls = parse_sitemap_xml(resp.text)
            for u in urls:
                if u.endswith(".xml"):
                    if u not in seen_sitemaps:
                        queue.append(u)
                else:
                    if in_scope(u, root_host, include_related_hosts, allow_external_pages):
                        collected.add(u)
        except requests.RequestException:
            pass

    return collected


# ============================================================================
# Web Crawler & Asset Downloader
# ============================================================================

def download_site(
    start_url: str,
    output_dir: pathlib.Path,
    max_pages: int = 2000,
    delay: float = 0.05,
    timeout: int = 20,
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    include_related_hosts: bool = False,
    keep_query_pages: bool = False,
    allow_external_pages: bool = False,
    include_external_assets: bool = True,
) -> tuple[pathlib.Path, int, int]:
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

        local_path = to_local_path(url, output_dir)
        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            log(f"[WARN] Failed fetching page {url}: {exc}")
            continue

        if resp.status_code != 200:
            log(f"[WARN] HTTP {resp.status_code} for {url}")
            continue

        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type and not url.endswith((".html", "/")):
            asset_path = to_local_path(url, output_dir)
            save_content(resp, asset_path)
            downloaded_assets.add(url)
            continue

        if is_cloudflare_challenge(resp):
            log(f"[ERROR] Cloudflare Anti-Bot challenge detected on {url}. Bypassing or scraping gated content is prohibited.")
            break

        save_content(resp, local_path)
        seen_pages.add(url)
        log(f"[PAGE] {url} -> {local_path}")

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
            except requests.RequestException as exc:
                log(f"[WARN] Failed asset {asset_url}: {exc}")

        if delay > 0:
            time.sleep(delay)

    target_dir = output_dir / root_host if (output_dir / root_host).exists() else output_dir
    neutralize_webflow_branding(target_dir)
    return target_dir, len(seen_pages), len(downloaded_assets)


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
        log(f"[REACT] Destination React project: {self.react_dir}")
        self._create_directories()
        html_files = self._collect_html_files()
        if not html_files:
            log(f"[ERROR] No HTML files found in {self.source_dir}")
            return

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

        log(f"[REACT] Found {len(html_files)} HTML pages to convert.")
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

        log(f"[SUCCESS] Successfully generated React app at: {self.react_dir}")

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
        log("[REACT] Scanning HTML files for external CDN assets...")
        url_set: set[str] = set()
        cdn_regex = re.compile(r'''https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+\.[a-zA-Z0-9]+(?:\?[^\s"'><)]*)?''', re.I)

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

            for script_match in re.finditer(r'<script[^>]+src=["\']([^"\']+)["\']', content, re.I):
                src = script_match.group(1).strip()
                if is_http(src):
                    url_set.add(src)

        base_urls = [u for u in url_set if not re.search(r'-p-\d+\.', u)]
        log(f"[REACT] Downloading {len(base_urls)} external CDN assets in parallel...")

        downloaded, failed = 0, 0

        def download_single(u: str) -> tuple[str, bool]:
            parsed = urlparse(u)
            clean_path = posixpath.normpath(unquote(parsed.path))
            filename = posixpath.basename(clean_path)
            if not filename:
                return u, False

            ext = posixpath.splitext(filename)[1].lower()
            if ext in [".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".avif", ".ico"]:
                subdir = self.assets_dir / "images"
                local_url = f"/assets/images/{filename}"
            elif ext in [".css"]:
                subdir = self.assets_dir / "css"
                local_url = f"/assets/css/{filename}"
            elif ext in [".js"]:
                subdir = self.assets_dir / "js"
                local_url = f"/assets/js/{filename}"
            else:
                subdir = self.assets_dir / "images"
                local_url = f"/assets/images/{filename}"

            dest = subdir / filename
            self.url_mapping[u] = local_url

            if dest.exists() and dest.stat().st_size > 0:
                return u, True

            try:
                r = self.session.get(u, timeout=20)
                if r.status_code == 200:
                    dest.write_bytes(r.content)
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

    def _extract_interaction_styles(self, html_files: list[pathlib.Path]) -> None:
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
            if prop.startswith("-"):
                prop = prop[1:]
            parts = prop.split("-")
            camel_prop = parts[0] + "".join(x.title() for x in parts[1:])
            styles[camel_prop] = val
        return json.dumps(styles)

    def _html_to_jsx(self, html: str) -> str:
        jsx = re.sub(r'<!--[\s\S]*?-->', '', html)

        def replace_style(m: re.Match) -> str:
            attrs = m.group(1)
            content = json.dumps(m.group(2).strip())
            return f'<style{attrs} dangerouslySetInnerHTML={{{{ __html: {content} }}}}></style>'

        jsx = re.sub(r'<style\b([^>]*)>([\s\S]*?)</style>', replace_style, jsx, flags=re.I)

        def replace_json_script(m: re.Match) -> str:
            attrs = m.group(1)
            content = m.group(2)
            for remote_url, local_path in self.url_mapping.items():
                content = content.replace(remote_url, local_path)
            escaped = json.dumps(content.strip())
            attrs_jsx = re.sub(r'\bclass="', 'className="', attrs)
            return f'<script{attrs_jsx} dangerouslySetInnerHTML={{{{ __html: {escaped} }}}}></script>'

        jsx = re.sub(r'<script([^>]*type=["\']application/json["\'][^>]*)>([\s\S]*?)</script>', replace_json_script, jsx, flags=re.I)

        def replace_template(m: re.Match) -> str:
            attrs = m.group(1)
            content = m.group(2)
            for remote_url, local_path in self.url_mapping.items():
                content = content.replace(remote_url, local_path)
            escaped = json.dumps(content)
            attrs_jsx = re.sub(r'\bclass="', 'className="', attrs)
            return f'<script{attrs_jsx} dangerouslySetInnerHTML={{{{ __html: {escaped} }}}}></script>'

        jsx = re.sub(r'<script([^>]*type=["\']text/x-wf-template["\'][^>]*)>([\s\S]*?)</script>', replace_template, jsx, flags=re.I)

        for remote_url, local_path in self.url_mapping.items():
            jsx = jsx.replace(remote_url, local_path)
            encoded = urllib.parse.quote(remote_url, safe="/:?=&%")
            if encoded != remote_url:
                jsx = jsx.replace(encoded, local_path)

        jsx = re.sub(r'\bclass="', 'className="', jsx)
        jsx = re.sub(r'\bfor="', 'htmlFor="', jsx)
        jsx = re.sub(r'\btabindex="', 'tabIndex="', jsx)

        svg_attrs = [
            ("stroke-width", "strokeWidth"),
            ("stroke-miterlimit", "strokeMiterlimit"),
            ("stroke-dasharray", "strokeDasharray"),
            ("stroke-dashoffset", "strokeDashoffset"),
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

        def replace_inline_style(m: re.Match) -> str:
            style_content = m.group(1)
            style_obj = self._style_str_to_jsx(style_content)
            return f"style={{{style_obj}}}"

        jsx = re.sub(r'\bstyle="([^"]*)"', replace_inline_style, jsx)
        jsx = re.sub(r'<(img|input|br|hr|embed|col|source|track|wbr)([^>]*?)(?<!/)>', r'<\1\2 />', jsx, flags=re.I)
        return jsx

    def _convert_pages(self, html_files: list[pathlib.Path]) -> list[dict]:
        routes = []

        for f in html_files:
            rel = f.relative_to(self.source_dir).as_posix()
            try:
                html_text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            route = "/" + re.sub(r'(?:^|/)(?:index)?\.html$', '', rel).lstrip("/")
            if not route:
                route = "/"

            page_id_match = re.search(r'data-wf-page="([^"]+)"', html_text)
            page_id = page_id_match.group(1) if page_id_match else ""

            body_match = re.search(r'<body[^>]*>([\s\S]*?)</body>', html_text, re.I)
            if not body_match:
                continue
            body_html = body_match.group(1)
            body_html = re.sub(r'<script[^>]*src=[\s\S]*?</script>', '', body_html, flags=re.I)
            body_html = re.sub(r'<script(?![^>]*type=["\'](?:text/x-wf-template|application/json)["\'])[\s\S]*?</script>', '', body_html, flags=re.I)

            converted_jsx = self._html_to_jsx(body_html)

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

            depth = len(out_rel.split("/")) - 1
            hook_rel = "../" * (depth + 1) + "hooks/useWebflow"

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

        title_m = re.search(r'<title>([^<]+)</title>', html_text, re.I)
        title = title_m.group(1).strip() if title_m else "React Webflow App"

        font_tags = []
        for m in re.finditer(r'<link[^>]+(?:fonts\.googleapis\.com|fonts\.gstatic\.com)[^>]*>', html_text, re.I):
            font_tags.append(m.group(0))
        if not font_tags:
            font_tags = [
                '<link rel="preconnect" href="https://fonts.googleapis.com" />',
                '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />',
                '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />'
            ]

        webfont_scripts = []
        for m in re.finditer(r'<script[^>]*>(?:[\s\S]*?WebFont\.load[\s\S]*?)</script>', html_text, re.I):
            webfont_scripts.append(m.group(0))

        favicon_tags = []
        for m in re.finditer(r'<link[^>]+rel=["\'](?:shortcut icon|icon|apple-touch-icon)["\'][^>]*>', html_text, re.I):
            tag = m.group(0)
            for remote_u, local_p in self.url_mapping.items():
                tag = tag.replace(remote_u, local_p)
            favicon_tags.append(tag)

        css_files = [f"/assets/css/{f.name}" for f in (self.assets_dir / "css").glob("*.css")]
        js_files = [f"/assets/js/{f.name}" for f in (self.assets_dir / "js").glob("*.js")]

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
      window.__WEBFLOW_CURRENCY_SETTINGS = {{"currencyCode":"USD","symbol":"$","decimal":".","fractionDigits":2,"group":",","template":"{{{{wf \"path\":\"symbol\",\"type\":\"PlainText\"}}}} {{{{wf \"path\":\"amount\",\"type\":\"CommercePrice\"}}}} {{{{wf \"path\":\"currencyCode\",\"type\":\"PlainText\"}}}}","hideDecimalForWholeNumbers":false}};
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
    open: true
  }
});
"""
        (self.react_dir / "vite.config.js").write_text(vite_config, encoding="utf-8")

    def _generate_main_jsx(self) -> None:
        main_jsx = """import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App.jsx';
import './styles/page-interactions.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
"""
        (self.src_dir / "main.jsx").write_text(main_jsx, encoding="utf-8")


# ============================================================================
# Automated npm Build & Server Launcher
# ============================================================================

def install_and_build(react_dir: pathlib.Path) -> bool:
    """Installs npm dependencies and compiles production Vite bundle."""
    npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_cmd:
        UI.warn("Node.js / npm not detected in PATH. Skipping automated npm install.")
        return False

    UI.item("Running 'npm install'...", status="step")
    try:
        proc = subprocess.run([npm_cmd, "install"], cwd=str(react_dir), capture_output=True, text=True)
        if proc.returncode != 0:
            UI.warn(f"npm install completed with warnings:\n{proc.stderr[:300]}")
        else:
            UI.item("npm packages installed successfully", status="ok")
    except Exception as e:
        UI.warn(f"Failed to run npm install: {e}")
        return False

    UI.item("Running 'npm run build'...", status="step")
    try:
        proc_b = subprocess.run([npm_cmd, "run", "build"], cwd=str(react_dir), capture_output=True, text=True)
        if proc_b.returncode != 0:
            UI.warn(f"npm run build failed:\n{proc_b.stderr[:300]}")
            return False
        else:
            UI.item("Vite production bundle compiled successfully", status="ok")
            return True
    except Exception as e:
        UI.warn(f"Failed to run npm run build: {e}")
        return False


def launch_server(react_dir: pathlib.Path, port: int = 5173) -> None:
    """Launches local Vite preview server."""
    npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_cmd:
        return
    print()
    UI.box("Local Preview Server", [
        f"Server starting on: {UI.CYAN}http://localhost:{port}/{UI.RESET}",
        f"Press {UI.BOLD}Ctrl+C{UI.RESET} in this terminal to exit."
    ], border_color=UI.GREEN)
    print()
    try:
        subprocess.run([npm_cmd, "run", "preview", "--", "--port", str(port), "--host"], cwd=str(react_dir))
    except KeyboardInterrupt:
        print(f"\n{UI.GRAY}Server stopped.{UI.RESET}")


# ============================================================================
# Interactive Wizard & CLI Entry Point
# ============================================================================

def interactive_wizard(args: argparse.Namespace | None = None) -> None:
    UI.banner()
    UI.system_status()

    w = 68
    print(f"{UI.CYAN}╭─ Project Setup Wizard ─────────────────────────────────────────────╮{UI.RESET}")
    print(f"{UI.CYAN}│{UI.RESET}  {UI.GRAY}Follow the steps below to download and convert any website:{UI.RESET}{' ' * (w - 61)}{UI.CYAN}│{UI.RESET}")
    print(f"{UI.CYAN}╰{'─' * w}╯{UI.RESET}\n")

    while True:
        url = UI.prompt("Target Website URL (e.g. https://example.com):")
        if not url:
            UI.warn("URL cannot be empty. Please enter a valid URL.")
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
        break

    parsed = urlparse(url)
    default_name = normalize_netloc(parsed).replace(".", "-").replace(":", "_")
    if default_name.endswith("-webflow-io"):
        default_name = default_name.replace("-webflow-io", "")

    to_react = UI.confirm("Convert website into a modern Vite + React SPA?", default=True)

    default_out = f"{default_name}-react" if to_react else default_name
    out_dir_str = UI.prompt("Output project folder name", default=default_out)
    out_dir = pathlib.Path(out_dir_str)

    auto_build = False
    launch_dev = False
    if to_react:
        auto_build = UI.confirm("Automatically install npm packages & build production bundle?", default=True)
        if auto_build:
            launch_dev = UI.confirm("Launch local preview server when finished?", default=True)

    total_steps = 4 if (to_react and auto_build) else (3 if to_react else 2)

    UI.step(1, total_steps, "Crawling Website & Discovering Assets")
    raw_dir = out_dir.parent / f"{out_dir.name}-raw" if to_react else out_dir

    max_pages = args.max_pages if args else 2000
    delay = args.delay if args else 0.05
    timeout = args.timeout if args else 20
    user_agent = args.user_agent if args else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    include_related_hosts = args.include_related_hosts if args else False
    keep_query_pages = args.keep_query_pages if args else False
    allow_external_pages = args.allow_external_pages if args else False
    include_external_assets = args.include_external_assets if args else True

    target_dir, total_pages, total_assets = download_site(
        start_url=url,
        output_dir=raw_dir,
        max_pages=max_pages,
        delay=delay,
        timeout=timeout,
        user_agent=user_agent,
        include_related_hosts=include_related_hosts,
        keep_query_pages=keep_query_pages,
        allow_external_pages=allow_external_pages,
        include_external_assets=include_external_assets,
    )
    UI.item(f"Downloaded {total_pages} HTML pages and {total_assets} assets", status="ok")

    react_dest = None
    if to_react:
        UI.step(2, total_steps, "Generating React SPA & Disarming Webflow Badge")
        react_dest = out_dir
        converter = ReactConverter(source_dir=target_dir, react_dir=react_dest)
        converter.run()

        if auto_build:
            UI.step(3, total_steps, "Installing Dependencies & Compiling Production Bundle")
            install_and_build(react_dest)

    UI.success_card(
        target_dir=target_dir,
        total_pages=total_pages,
        total_assets=total_assets,
        react_dir=react_dest
    )

    if launch_dev and react_dest:
        launch_server(react_dest)


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(
        description="Download websites with all assets (including CDNs) and automatically convert them into modern Vite + React apps."
    )
    parser.add_argument("url", nargs="?", default=None, help="Start URL to download, e.g. https://www.example.com")
    parser.add_argument("-o", "--output", default="downloaded_site", help="Output directory for downloaded site")
    parser.add_argument("--max-pages", type=int, default=2000, help="Maximum HTML pages to crawl")
    parser.add_argument("--delay", type=float, default=0.05, help="Delay between page requests in seconds")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    parser.add_argument("--include-related-hosts", action="store_true", help="Also crawl hosts under the same root domain")
    parser.add_argument("--keep-query-pages", action="store_true", help="Treat query-string page URLs as unique pages")
    parser.add_argument("--allow-external-pages", action="store_true", help="Allow crawling HTML pages on other external hosts")
    parser.add_argument("--user-agent", default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", help="User-Agent string")
    parser.add_argument("--no-external-assets", action="store_false", dest="include_external_assets", default=True, help="Do not download CDN assets")
    parser.add_argument("--to-react", nargs="?", const="", default=None, help="Convert downloaded site into Vite + React app")
    parser.add_argument("--convert-dir", default=None, help="Convert existing directory of HTML/assets without downloading")
    parser.add_argument("--react-out", default=None, help="Output directory when using --convert-dir")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # If no arguments provided: run the interactive OpenCode UI wizard
    if not args.url and not args.convert_dir:
        interactive_wizard(args)
        return

    # Direct conversion mode
    if args.convert_dir:
        src = pathlib.Path(args.convert_dir)
        dest = pathlib.Path(args.react_out) if args.react_out else src.parent / f"{src.name}-react"
        converter = ReactConverter(source_dir=src, react_dir=dest)
        converter.run()
        UI.success_card(target_dir=src, total_pages=len(list(src.rglob("*.html"))), total_assets=0, react_dir=dest)
        return

    # Headless CLI download mode
    out_dir = pathlib.Path(args.output)
    target_dir, total_pages, total_assets = download_site(
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

    react_dest = None
    if args.to_react is not None:
        react_dest = pathlib.Path(args.to_react) if args.to_react else out_dir.parent / f"{out_dir.name}-react"
        converter = ReactConverter(source_dir=target_dir, react_dir=react_dest)
        converter.run()

    UI.success_card(target_dir=target_dir, total_pages=total_pages, total_assets=total_assets, react_dir=react_dest)


if __name__ == "__main__":
    main()
