import re
import time
import logging
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://suumo.jp"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}
REQUEST_DELAY = 2.0  # seconds between requests


def _parse_price(text: str) -> int | None:
    """
    価格文字列を円単位の整数に変換する。
    例: "5,980万円" -> 59800000, "1億2,000万円" -> 120000000
    """
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


class SuumoScraper:
    def search_by_area(self, search_url: str, max_price: int | None = None) -> list[dict]:
        """
        SUUMO 検索結果URLからすべてのページを巡回して物件リストを返す。
        Returns list of dicts: {id, name, price, address, url, source}
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

            # 次ページへのリンクを探す
            page_url = self._next_page_url(soup, page_url)
            if page_url:
                time.sleep(REQUEST_DELAY)

        logger.info(f"Found {len(listings)} listings from SUUMO area search")
        return listings

    def get_property(self, url: str) -> dict | None:
        """特定物件URLから現在の価格情報を取得する。"""
        session = requests.Session()
        soup = _fetch(url, session)
        if soup is None:
            return None

        # 詳細ページから物件名・価格を取得
        name = ""
        name_tag = soup.select_one("h1.section_h1-header-title, h1.bukkenTitle, h1")
        if name_tag:
            name = name_tag.get_text(strip=True)

        price = None
        for sel in [".price", ".bukkenPrice", "[class*='price']"]:
            tag = soup.select_one(sel)
            if tag:
                price = _parse_price(tag.get_text())
                if price:
                    break

        address = ""
        for sel in [".bukkenSpec th:-soup-contains('所在地') + td",
                    "th:-soup-contains('所在地') + td"]:
            try:
                tag = soup.select_one(sel)
                if tag:
                    address = tag.get_text(strip=True)
                    break
            except Exception:
                pass

        if price is None:
            logger.warning(f"Could not parse price for {url}")
            return None

        return {
            "id": f"suumo:{urlparse(url).path.rstrip('/').split('/')[-1]}",
            "name": name,
            "price": price,
            "address": address,
            "url": url,
            "source": "suumo",
        }

    def _parse_list_page(self, soup: BeautifulSoup, max_price: int | None) -> list[dict]:
        listings = []

        # SUUMO の物件カード候補セレクタ（サイト改修に備えて複数試す）
        cards = (
            soup.select("div.property_unit")
            or soup.select("li.property_unit")
            or soup.select("[class*='cassette']")
            or soup.select("div.js-cassette_link")
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
        # 物件リンク・名前
        link_tag = (
            card.select_one("a.property_unit-title")
            or card.select_one(".property_unit-summary a")
            or card.select_one("h2 a, h3 a")
            or card.select_one("a[href*='/ms/']")
            or card.select_one("a[href*='/chuko/']")
            or card.select_one("a[href*='/shinchiku/']")
        )
        if link_tag is None:
            return None

        href = link_tag.get("href", "")
        if not href:
            return None
        url = urljoin(BASE_URL, href)
        name = link_tag.get_text(strip=True)

        # 価格
        price_tag = (
            card.select_one(".property_unit-price")
            or card.select_one(".dottable-vm .dottable-bd")
            or card.select_one("[class*='price']")
            or card.select_one("dd.ui-text--bold")
        )
        if price_tag is None:
            # テーブル形式の場合
            for dt in card.select("dt, th"):
                if "価格" in dt.get_text():
                    sibling = dt.find_next_sibling(["dd", "td"])
                    if sibling:
                        price_tag = sibling
                        break

        price = _parse_price(price_tag.get_text()) if price_tag else None
        if price is None:
            return None

        # 所在地
        address = ""
        for dt in card.select("dt, th"):
            if "所在地" in dt.get_text() or "住所" in dt.get_text():
                sibling = dt.find_next_sibling(["dd", "td"])
                if sibling:
                    address = sibling.get_text(strip=True)
                    break

        # ID: URL のパス末尾を使う
        path = urlparse(url).path.rstrip("/").split("/")[-1]
        prop_id = f"suumo:{path}"

        return {
            "id": prop_id,
            "name": name,
            "price": price,
            "address": address,
            "url": url,
            "source": "suumo",
        }

    def _next_page_url(self, soup: BeautifulSoup, current_url: str) -> str | None:
        """次ページへのリンクを返す。なければ None。"""
        next_tag = (
            soup.select_one("a[rel='next']")
            or soup.select_one("a.pagination-next")
            or soup.select_one("li.pagination-next a")
            or soup.select_one("a:-soup-contains('次へ')")
            or soup.select_one("a:-soup-contains('次の')")
        )
        if next_tag:
            href = next_tag.get("href", "")
            if href:
                return urljoin(current_url, href)
        return None
