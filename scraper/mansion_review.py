import re
import time
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.mansion-review.jp"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}
REQUEST_DELAY = 2.0


def _parse_price(text: str) -> int | None:
    if not text:
        return None
    text = text.replace(",", "").replace(" ", "").replace("　", "")

    oku = 0
    man = 0
    m = re.search(r"(\d+)億", text)
    if m:
        oku = int(m.group(1))
    m = re.search(r"(\d+)万", text)
    if m:
        man = int(m.group(1))

    if oku == 0 and man == 0:
        return None
    return oku * 100_000_000 + man * 10_000


def _fetch(url: str, session: requests.Session) -> BeautifulSoup | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as e:
        logger.warning(f"Fetch failed: {url} -> {e}")
        return None


class MansionReviewScraper:
    def search_by_area(self, search_url: str, max_price: int | None = None) -> list[dict]:
        """
        マンションレビュー 検索結果URLからすべてのページを巡回して物件リストを返す。
        """
        session = requests.Session()
        listings = []
        page_url = search_url

        while page_url:
            logger.info(f"Fetching: {page_url}")
            soup = _fetch(page_url, session)
            if soup is None:
                break

            page_listings = self._parse_list_page(soup, max_price)
            listings.extend(page_listings)

            page_url = self._next_page_url(soup, page_url)
            if page_url:
                time.sleep(REQUEST_DELAY)

        logger.info(f"Found {len(listings)} listings from MansionReview area search")
        return listings

    def get_property(self, url: str) -> dict | None:
        """特定物件URLから現在の価格情報を取得する。"""
        session = requests.Session()
        soup = _fetch(url, session)
        if soup is None:
            return None

        name = ""
        name_tag = soup.select_one("h1")
        if name_tag:
            name = name_tag.get_text(strip=True)

        price = None
        for sel in ["[class*='price']", "[class*='Price']"]:
            tag = soup.select_one(sel)
            if tag:
                price = _parse_price(tag.get_text())
                if price:
                    break

        if price is None:
            logger.warning(f"Could not parse price for {url}")
            return None

        path = urlparse(url).path.rstrip("/").split("/")[-1]
        return {
            "id": f"mansion_review:{path}",
            "name": name,
            "price": price,
            "address": "",
            "url": url,
            "source": "mansion_review",
        }

    def _parse_list_page(self, soup: BeautifulSoup, max_price: int | None) -> list[dict]:
        listings = []

        # マンションレビューの物件カード候補セレクタ
        cards = (
            soup.select("div.property-card")
            or soup.select("li.property-item")
            or soup.select("[class*='mansion-item']")
            or soup.select("[class*='property']")
        )

        for card in cards:
            listing = self._parse_card(card)
            if listing is None:
                continue
            if max_price and listing["price"] > max_price:
                continue
            listings.append(listing)

        return listings

    def _parse_card(self, card: BeautifulSoup) -> dict | None:
        link_tag = (
            card.select_one("a[href*='/mansion/']")
            or card.select_one("a[href*='/chuko/']")
            or card.select_one("h2 a, h3 a, h4 a")
            or card.select_one("a")
        )
        if link_tag is None:
            return None

        href = link_tag.get("href", "")
        if not href:
            return None
        url = urljoin(BASE_URL, href)
        name = link_tag.get_text(strip=True)

        price_tag = card.select_one(
            "[class*='price'], [class*='Price'], [class*='kakaku']"
        )
        price = _parse_price(price_tag.get_text()) if price_tag else None
        if price is None:
            return None

        address = ""
        addr_tag = card.select_one("[class*='address'], [class*='addr'], [class*='location']")
        if addr_tag:
            address = addr_tag.get_text(strip=True)

        path = urlparse(url).path.rstrip("/").split("/")[-1]
        prop_id = f"mansion_review:{path}"

        return {
            "id": prop_id,
            "name": name,
            "price": price,
            "address": address,
            "url": url,
            "source": "mansion_review",
        }

    def _next_page_url(self, soup: BeautifulSoup, current_url: str) -> str | None:
        next_tag = (
            soup.select_one("a[rel='next']")
            or soup.select_one("a.next")
            or soup.select_one("a:-soup-contains('次へ')")
            or soup.select_one("a:-soup-contains('次の')")
        )
        if next_tag:
            href = next_tag.get("href", "")
            if href:
                return urljoin(current_url, href)
        return None
