import io
import requests
from pypdf import PdfReader
from sports.nba_injury_official import fetch_latest_pdf_link, base_headers

url = fetch_latest_pdf_link()
print({'pdf_url': url})
resp = requests.get(url, headers=base_headers(), timeout=30)
resp.raise_for_status()
reader = PdfReader(io.BytesIO(resp.content))
for i, page in enumerate(reader.pages[:2], start=1):
    text = page.extract_text() or ''
    print('\n' + '='*40)
    print('PAGE', i)
    print('='*40)
    print(text[:8000])
