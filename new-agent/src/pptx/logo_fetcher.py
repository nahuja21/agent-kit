"""
Client Logo Fetcher with Multiple Strategies.

Fetches company logos using a reliable multi-strategy approach:
1. Clearbit Logo API (most reliable for known companies)
2. Google Favicon API (always works for any domain)
3. Direct website scraping (og:image, logo tags)

Usage:
    fetcher = LogoFetcher()
    logo_path = fetcher.fetch_logo("Advantia Health")
    if logo_path:
        # Use the logo
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests


class LogoFetcher:
    """
    Fetches company logos using multiple reliable strategies.
    
    Strategy order:
    1. Clearbit Logo API - best quality, works for most companies
    2. Google Favicon API - always returns something for valid domains
    3. Website og:image scraping - finds social share images
    """
    
    # API endpoints
    CLEARBIT_URL = "https://logo.clearbit.com/{domain}"
    GOOGLE_FAVICON_URL = "https://www.google.com/s2/favicons?domain={domain}&sz=128"
    
    # Common domain suffixes to try
    DOMAIN_SUFFIXES = [".com", ".io", ".co", ".health", ".org", ".net", ".us"]
    
    # Words to remove from company names when guessing domain
    COMPANY_SUFFIXES = [
        "inc", "llc", "ltd", "corp", "corporation", "company", "co",
        "holdings", "group", "partners", "consulting", "services",
        "solutions", "technologies", "tech", "healthcare", "health"
    ]
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize the logo fetcher.
        
        Args:
            cache_dir: Directory to cache downloaded logos (optional)
        """
        self.cache_dir = cache_dir or Path(__file__).parent.parent.parent / "logos"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        self._debug_log: list[str] = []
    
    def fetch_logo(
        self, 
        company_name: str,
        company_website: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Optional[Path]:
        """
        Fetch a company logo using multiple strategies.
        
        Args:
            company_name: Name of the company
            company_website: Known website URL (if available)
            force_refresh: If True, re-download even if cached
            
        Returns:
            Path to the downloaded logo, or None if not found
        """
        self._debug_log = []
        
        if not company_name:
            self._debug_log.append("No company name provided")
            return None
        
        self._debug_log.append(f"Searching logo for: {company_name}")
        
        # Check cache first
        cache_key = self._get_cache_key(company_name)
        cached_path = self.cache_dir / f"{cache_key}.png"
        
        if cached_path.exists() and not force_refresh:
            self._debug_log.append(f"✓ Found in cache: {cached_path.name}")
            return cached_path
        
        # Generate domain guesses
        domains = self._guess_domains(company_name, company_website)
        self._debug_log.append(f"Trying domains: {domains[:5]}")
        
        logo_data = None
        found_via = None
        
        # Strategy 1: Try Clearbit for each domain (most reliable for real logos)
        for domain in domains:
            self._debug_log.append(f"  Clearbit: {domain}")
            logo_data = self._try_clearbit(domain)
            if logo_data:
                found_via = f"Clearbit ({domain})"
                break
        
        # NOTE: Disabled website scraping and Google favicon as they often return wrong images
        # Only Clearbit is reliable for actual company logos
        
        if not logo_data:
            self._debug_log.append("  Clearbit did not find logo - skipping client logo")
        
        # Save if found
        if logo_data:
            try:
                cached_path.write_bytes(logo_data)
                self._debug_log.append(f"✓ Logo found via {found_via}")
                self._debug_log.append(f"✓ Saved to: {cached_path.name}")
                return cached_path
            except Exception as e:
                self._debug_log.append(f"Save error: {e}")
        else:
            self._debug_log.append("✗ No logo found after trying all strategies")
        
        return None
    
    def get_debug_log(self) -> list[str]:
        """Get the debug log from the last fetch attempt."""
        return self._debug_log
    
    def _get_cache_key(self, company_name: str) -> str:
        """Generate a cache key from company name."""
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', company_name.lower())
        return hashlib.md5(clean_name.encode()).hexdigest()[:12]
    
    def _guess_domains(self, company_name: str, company_website: Optional[str] = None) -> list[str]:
        """
        Guess possible domain names from a company name.
        
        Examples:
            "Advantia Health" → ["advantiahealth.com", "advantia.com", ...]
        """
        domains = []
        
        # If website provided, use it first
        if company_website:
            domain = self._extract_domain(company_website)
            if domain:
                domains.append(domain)
        
        # Clean company name (keep all words first)
        name_lower = company_name.lower()
        
        # FIRST: Try full name without spaces (e.g., "advantiahealth")
        full_name_clean = re.sub(r'[^a-z0-9]', '', name_lower)
        for suffix in self.DOMAIN_SUFFIXES:
            domain = f"{full_name_clean}{suffix}"
            if domain not in domains:
                domains.append(domain)
        
        # THEN: Remove common company suffixes for more variations
        clean_name = name_lower
        for suffix in self.COMPANY_SUFFIXES:
            clean_name = re.sub(rf'\b{suffix}\b', '', clean_name)
        
        # Remove special characters and extra spaces
        clean_name = re.sub(r'[^a-z0-9\s]', '', clean_name)
        clean_name = ' '.join(clean_name.split())
        
        # Generate domain variations
        words = clean_name.split()
        
        if words:
            # Full name without spaces
            full_no_space = ''.join(words)
            
            # First word only
            first_word = words[0]
            
            # First two words
            first_two = ''.join(words[:2]) if len(words) >= 2 else full_no_space
            
            # Try each variation with common suffixes
            variations = [full_no_space, first_word, first_two]
            
            for var in variations:
                for suffix in self.DOMAIN_SUFFIXES:
                    domain = f"{var}{suffix}"
                    if domain not in domains:
                        domains.append(domain)
        
        return domains[:10]
    
    def _extract_domain(self, url: str) -> Optional[str]:
        """Extract domain from a URL."""
        try:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain if domain else None
        except Exception:
            return None
    
    def _try_clearbit(self, domain: str) -> Optional[bytes]:
        """Try to get a logo from Clearbit."""
        try:
            url = self.CLEARBIT_URL.format(domain=domain)
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '')
                if 'image' in content_type and len(response.content) > 500:
                    return response.content
            
            return None
        except Exception:
            return None
    
    def _try_google_favicon(self, domain: str) -> Optional[bytes]:
        """Try to get a favicon from Google."""
        try:
            url = self.GOOGLE_FAVICON_URL.format(domain=domain)
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                # Google returns a default icon for unknown domains
                # Real favicons are usually > 1000 bytes
                if len(response.content) > 500:
                    return response.content
            
            return None
        except Exception:
            return None
    
    def _try_website_scraping(self, domain: str) -> Optional[bytes]:
        """Try to scrape logo from the company website - more conservative approach."""
        try:
            # Try to get the homepage
            url = f"https://{domain}"
            response = self.session.get(url, timeout=15, allow_redirects=True)
            
            if response.status_code != 200:
                return None
            
            html = response.text
            
            # Look for logo in specific patterns (NOT og:image - those are often banners)
            # Prioritize images with "logo" in the class, alt, or filename
            logo_patterns = [
                # Class contains "logo" and not "footer" or "partner"
                r'<img[^>]+class=["\'][^"\']*\blogo\b[^"\']*["\'][^>]+src=["\']([^"\']+)["\']',
                r'<img[^>]+src=["\']([^"\']+)["\'][^>]+class=["\'][^"\']*\blogo\b[^"\']*["\']',
                # Alt contains company name + logo
                r'<img[^>]+alt=["\'][^"\']*logo[^"\']*["\'][^>]+src=["\']([^"\']+)["\']',
                # Filename contains "logo" but not "partner" or "client"
                r'<img[^>]+src=["\']([^"\']*[/-]logo[^"\']*\.(?:png|jpg|svg|webp))["\']',
            ]
            
            for pattern in logo_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for img_url in matches:
                    # Skip if it looks like a partner/client logo
                    if any(skip in img_url.lower() for skip in ['partner', 'client', 'footer', 'social', 'icon-', 'favicon']):
                        continue
                    
                    if not img_url.startswith('http'):
                        img_url = f"https://{domain}{img_url}" if img_url.startswith('/') else f"https://{domain}/{img_url}"
                    
                    try:
                        img_response = self.session.get(img_url, timeout=10)
                        if img_response.status_code == 200:
                            content = img_response.content
                            # Logo should be reasonably sized (not too big like a banner)
                            if 1000 < len(content) < 500000:
                                self._debug_log.append(f"    Found logo: {img_url[:50]}...")
                                return content
                    except Exception:
                        continue
            
            return None
        except Exception:
            return None
    
    def clear_cache(self) -> None:
        """Clear the logo cache."""
        if self.cache_dir.exists():
            for f in self.cache_dir.glob("*.png"):
                try:
                    f.unlink()
                except Exception:
                    pass
