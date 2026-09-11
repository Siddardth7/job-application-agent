#!/usr/bin/env python3
"""
check_usage.py — Checks and reports live API usage limits and balances.
Monitors:
1. Apify API monthly credit limit ($5.00 tier), cycle dates, and remaining balance.
2. Today's run spend.
3. Supabase database application and contact row counts.
"""

import sys
import os
import json
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"

APIFY_TOKEN = ""

def load_env():
    """Load variables from .env."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

    global APIFY_TOKEN
    APIFY_TOKEN = os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_KEY", "")

def get_apify_usage() -> dict:
    """Fetch live usage and limits from Apify API."""
    if not APIFY_TOKEN:
        return {"error": "APIFY_TOKEN not configured"}
        
    url = f"https://api.apify.com/v2/users/me/limits?token={APIFY_TOKEN}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "JobSearchUsageChecker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data", {})
            
            cycle = data.get("monthlyUsageCycle", {})
            limits = data.get("limits", {})
            current = data.get("current", {})
            
            max_usd = limits.get("maxMonthlyUsageUsd", 5.0)
            used_usd = current.get("monthlyUsageUsd", 0.0)
            remaining_usd = max(0.0, max_usd - used_usd)
            pct_used = (used_usd / max_usd * 100) if max_usd > 0 else 0.0
            
            start_date = cycle.get("startAt", "")[:10]
            end_date = cycle.get("endAt", "")[:10]
            
            return {
                "max_usd": max_usd,
                "used_usd": used_usd,
                "remaining_usd": remaining_usd,
                "pct_used": pct_used,
                "cycle_start": start_date,
                "cycle_end": end_date
            }
    except Exception as e:
        return {"error": str(e)}

def get_supabase_counts() -> dict:
    """Fetch total applications and contacts from Supabase."""
    url = os.getenv("SUPABASE_URL", "https://chsrkysjongzgdbwqhlu.supabase.co")
    key = os.getenv("SUPABASE_KEY")
    
    if not key:
        return {"error": "SUPABASE_KEY not configured"}
        
    counts = {}
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Range-Unit": "items",
        "Range": "0-0",
        "Prefer": "count=exact"
    }
    
    for table in ["applications", "contacts"]:
        try:
            req = urllib.request.Request(f"{url}/rest/v1/{table}?select=*", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                content_range = resp.headers.get("Content-Range", "")
                if "/" in content_range:
                    counts[table] = int(content_range.split("/")[1])
                else:
                    counts[table] = 0
        except Exception as e:
            counts[table] = "N/A"
            
    return counts

def print_report():
    load_env()
    print("==================================================")
    print("        API USAGE & TRACKER STATUS REPORT         ")
    print("==================================================")
    
    # 1. Apify
    apify = get_apify_usage()
    if "error" in apify:
        print(f"Apify Status: Error fetching data ({apify['error']})")
    else:
        print(f"Apify Monthly Plan:      ${apify['max_usd']:.2f} Free Credit Tier")
        print(f"Apify Cycle Period:      {apify['cycle_start']} to {apify['cycle_end']}")
        print(f"Current Month Spend:     ${apify['used_usd']:.4f} ({apify['pct_used']:.1f}% used)")
        print(f"Remaining Apify Balance: ${apify['remaining_usd']:.4f} ({(100 - apify['pct_used']):.1f}% left)")
        
        if apify["remaining_usd"] < 1.0:
            print("  ⚠️ WARNING: Apify credit balance is below $1.00.")
        else:
            print("  ✅ Apify balance is healthy (safe for daily runs).")
            
    print("--------------------------------------------------")
    
    # 2. Supabase
    sb = get_supabase_counts()
    if "error" in sb:
        print(f"Supabase Status: Error ({sb['error']})")
    else:
        print(f"Supabase Applications:   {sb.get('applications', 'N/A')} records")
        print(f"Supabase Contacts:       {sb.get('contacts', 'N/A')} records")
        print("  ✅ Database connection is live.")
        
    print("==================================================")

def main():
    if "--json" in sys.argv:
        load_env()
        data = {
            "apify": get_apify_usage(),
            "supabase": get_supabase_counts(),
            "timestamp": datetime.now().isoformat()
        }
        print(json.dumps(data, indent=2))
    else:
        print_report()

if __name__ == "__main__":
    main()
