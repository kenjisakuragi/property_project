import json
import logging
import sys
from pathlib import Path

import yaml

import notifier
from scraper import get_scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.yaml")
HISTORY_PATH = Path("data/prices.json")


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {}
    with open(HISTORY_PATH, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_history(history: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def process_alert(alert: dict, history: dict) -> list[dict]:
    source = alert.get("source", "suumo")
    alert_type = alert.get("type", "area")
    alert_name = alert.get("name", "")
    notify_on = set(alert.get("notify_on", ["price_drop"]))
    max_price = alert.get("max_price")

    scraper = get_scraper(source)
    found_alerts = []

    if alert_type == "area":
        search_url = alert.get("search_url", "")
        if not search_url:
            logger.warning(f"[{alert_name}] search_url が設定されていません")
            return []

        listings = scraper.search_by_area(search_url, max_price=max_price)
        logger.info(f"[{alert_name}] {len(listings)} 件取得")

        for listing in listings:
            prop_id = listing["id"]
            prev = history.get(prop_id)

            if prev is None:
                # 新着物件
                if "new_listing" in notify_on:
                    found_alerts.append({
                        "kind": "new_listing",
                        "alert_name": alert_name,
                        **listing,
                    })
                    logger.info(f"  [新着] {listing['name']} {listing['price']:,}円")
            else:
                # 既知の物件: 価格変動チェック
                if "price_drop" in notify_on and listing["price"] < prev["price"]:
                    found_alerts.append({
                        "kind": "price_drop",
                        "alert_name": alert_name,
                        "prev_price": prev["price"],
                        **listing,
                    })
                    logger.info(
                        f"  [値下げ] {listing['name']} "
                        f"{prev['price']:,}円 → {listing['price']:,}円"
                    )

            # 履歴を更新
            history[prop_id] = {
                "price": listing["price"],
                "name": listing["name"],
                "url": listing["url"],
            }

    elif alert_type == "property":
        urls = alert.get("urls", [])
        for url in urls:
            listing = scraper.get_property(url)
            if listing is None:
                logger.warning(f"[{alert_name}] 物件情報を取得できませんでした: {url}")
                continue

            prop_id = listing["id"]
            prev = history.get(prop_id)

            if prev is None:
                logger.info(f"[{alert_name}] 初回取得: {listing['name']} {listing['price']:,}円")
            elif "price_drop" in notify_on and listing["price"] < prev["price"]:
                found_alerts.append({
                    "kind": "price_drop",
                    "alert_name": alert_name,
                    "prev_price": prev["price"],
                    **listing,
                })
                logger.info(
                    f"  [値下げ] {listing['name']} "
                    f"{prev['price']:,}円 → {listing['price']:,}円"
                )

            history[prop_id] = {
                "price": listing["price"],
                "name": listing["name"],
                "url": listing["url"],
            }

    return found_alerts


def main() -> None:
    logger.info("=== 不動産アラートチェック開始 ===")

    try:
        config = load_config()
    except Exception as e:
        logger.error(f"config.yaml の読み込みに失敗しました: {e}")
        sys.exit(1)

    history = load_history()
    all_alerts = []

    for alert in config.get("alerts", []):
        try:
            alerts = process_alert(alert, history)
            all_alerts.extend(alerts)
        except Exception as e:
            logger.error(f"[{alert.get('name')}] エラーが発生しました: {e}")

    logger.info(f"チェック完了: {len(all_alerts)} 件のアラートを検出")

    if all_alerts:
        try:
            notifier.send(config.get("email", {}), all_alerts)
        except Exception as e:
            logger.error(f"メール送信に失敗しました: {e}")
            # 送信失敗でも履歴は保存する
    else:
        logger.info("通知対象の物件はありませんでした")

    save_history(history)
    logger.info("価格履歴を保存しました")


if __name__ == "__main__":
    main()
