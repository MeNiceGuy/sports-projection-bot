import io
import requests
from pypdf import PdfReader
from sports.nba_injury_official import fetch_latest_pdf_link, base_headers


def main():
    url = fetch_latest_pdf_link()
    print({"pdf_url": url})
    resp = requests.get(url, headers=base_headers(), timeout=30)
    resp.raise_for_status()
    reader = PdfReader(io.BytesIO(resp.content))
    text = []
    for page in reader.pages[:3]:
        text.append(page.extract_text() or "")
    joined = "\n".join(text)
    print(joined[:5000])


if __name__ == "__main__":
    main()
