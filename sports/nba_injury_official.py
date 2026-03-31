from __future__ import annotations

import re
from urllib.parse import urljoin

import requests

OFFICIAL_PAGE = "https://official.nba.com/nba-injury-report-2025-26-season/"
PDF_NAME_PATTERN = re.compile(r"Injury-Report_\d{4}-\d{2}-\d{2}_.+?\.pdf", re.I)


def base_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/pdf",
        "Accept-Language": "en-US,en;q=0.9",
    }


def parse_pdf_datetime(url: str):
    m = re.search(r"Injury-Report_(\d{4}-\d{2}-\d{2})_([0-9_:\-]{1,8})(AM|PM)", url, re.I)
    if not m:
        return 0
    date_str, raw_time, meridiem = m.group(1), m.group(2), m.group(3).upper()
    digits = re.sub(r"\D", "", raw_time)
    if not digits:
        return 0
    if len(digits) <= 2:
        hour = int(digits)
        minute = 0
    else:
        hour = int(digits[:-2])
        minute = int(digits[-2:])
    if meridiem == "PM" and hour < 12:
        hour += 12
    if meridiem == "AM" and hour == 12:
        hour = 0
    return int(f"{date_str.replace('-', '')}{hour:02d}{minute:02d}")


def extract_pdf_links(html_text: str):
    links = set(re.findall(r'https://[^\"\']+Injury-Report_[^\"\']+\.pdf', html_text, re.I))
    if not links:
        for match in PDF_NAME_PATTERN.findall(html_text):
            links.add(urljoin(OFFICIAL_PAGE, match))
    return sorted(links)


def fetch_latest_pdf_link():
    session = requests.Session()
    resp = session.get(OFFICIAL_PAGE, headers=base_headers(), timeout=20)
    resp.raise_for_status()
    links = extract_pdf_links(resp.text)
    if not links:
        return None
    return sorted(links, key=parse_pdf_datetime, reverse=True)[0]
