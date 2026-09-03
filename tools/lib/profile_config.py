"""Search-profile config loader.

Every list that used to be hardcoded in gate_and_score.py / fetch_jobs.py lives in
config/search_profile.json, which `/setup` writes for each user. The example file is
the fallback so a fresh clone still runs before setup — but it carries the template
author's targets, so running the pipeline on it scores against the wrong profile.

ponytail: plain dict, no schema validation. Add one when a bad config actually bites.
"""

import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
USER_CONFIG = ROOT_DIR / "config" / "search_profile.json"
EXAMPLE_CONFIG = ROOT_DIR / "config" / "search_profile.example.json"

_cache = None


def load_config() -> dict:
    """Return the search profile. User config wins; example is the fallback."""
    global _cache
    if _cache is not None:
        return _cache
    path = USER_CONFIG if USER_CONFIG.exists() else EXAMPLE_CONFIG
    if not path.exists():
        raise FileNotFoundError(
            f"No search profile found. Expected {USER_CONFIG} or {EXAMPLE_CONFIG}. Run /setup."
        )
    with open(path, "r", encoding="utf-8") as f:
        _cache = json.load(f)
    _cache["_source"] = str(path.relative_to(ROOT_DIR))
    return _cache


def using_example_config() -> bool:
    """True when the pipeline is running on the template author's profile, not the user's."""
    return not USER_CONFIG.exists()


def classify_domain(company: str, title: str) -> str:
    """Map a posting to a domain label using the configured company/title keywords."""
    cfg = load_config()
    company_lower = (company or "").lower()
    title_lower = (title or "").lower()
    for domain in cfg.get("domains", []):
        if any(k in company_lower for k in domain.get("company_keywords", [])):
            return domain["name"]
    for domain in cfg.get("domains", []):
        if any(k in title_lower for k in domain.get("title_keywords", [])):
            return domain["name"]
    return cfg.get("default_domain", "Uncategorized")


def peer_role_keyword(title: str) -> str:
    """Pick the LinkedIn people-search role keyword for a posting title."""
    mapping = load_config().get("search", {}).get("peer_role_keywords", {})
    title_lower = (title or "").lower()
    for key, value in mapping.items():
        if key != "_default" and key in title_lower:
            return value
    return mapping.get("_default", "engineer")


def _or(terms: list) -> str:
    """('a' OR 'b') as a LinkedIn boolean group."""
    return "(" + " OR ".join(f'"{x}"' for x in terms if x) + ")"


def linkedin_query(keywords: str, location: str = "United States",
                   days: int = 7, experience: str = "2,3") -> str:
    """Build one LinkedIn jobs search URL. f_TPR is seconds; f_E is experience level."""
    import urllib.parse
    return ("https://www.linkedin.com/jobs/search/?keywords="
            + urllib.parse.quote_plus(keywords)
            + "&location=" + urllib.parse.quote_plus(location)
            + f"&f_TPR=r{days * 86400}&f_E={experience}")


def search_terms() -> dict:
    """Config-derived building blocks for the Apify passes."""
    cfg = load_config()
    search = cfg.get("search", {})
    domains = cfg.get("domains", [])
    return {
        "anchors": cfg.get("target_anchors", []),
        "titles": search.get("role_titles", []),
        "adjacent_titles": search.get("adjacent_titles", []),
        "toolkit": cfg.get("master_toolkit", [])[:8],
        "domain_companies": [c for d in domains for c in d.get("company_keywords", [])],
        "domain_titles": [k for d in domains for k in d.get("title_keywords", [])],
        "intl_locations": search.get("intl_locations", []),
    }


def demo() -> None:
    """Self-check: config loads and the classifiers route as configured."""
    cfg = load_config()
    assert cfg.get("master_toolkit"), "master_toolkit must not be empty"
    assert cfg.get("default_domain"), "default_domain is required"
    # A configured company keyword wins over the default bucket.
    first = cfg["domains"][0]
    if first.get("company_keywords"):
        probe = first["company_keywords"][0]
        assert classify_domain(probe, "Engineer") == first["name"], "company keyword routing broken"
    # An unknown company with an unknown title falls through to the default.
    assert classify_domain("Zzz Unknown Co", "Widget Polisher") == cfg["default_domain"]
    # Peer keyword falls back when no substring matches.
    mapping = cfg["search"]["peer_role_keywords"]
    assert peer_role_keyword("Totally Unrelated Title") == mapping["_default"]
    for key, value in mapping.items():
        if key != "_default":
            assert peer_role_keyword(f"Senior {key} specialist") == value, f"{key} routing broken"
    # Query builder produces a well-formed, correctly-escaped URL.
    q = linkedin_query('("Quality Engineer") AND ("SPC")', days=7)
    assert q.startswith("https://www.linkedin.com/jobs/search/?keywords=")
    assert "f_TPR=r604800" in q, "7 days must encode as 604800 seconds"
    assert " " not in q, "query must be URL-escaped"
    assert _or(["a", "b"]) == '("a" OR "b")'
    st = search_terms()
    assert st["titles"], "search.role_titles must not be empty"
    print(f"OK  profile_config self-check passed (source: {cfg['_source']})")


if __name__ == "__main__":
    demo()
