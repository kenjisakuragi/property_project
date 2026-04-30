from .suumo import SuumoScraper
from .mansion_review import MansionReviewScraper

def get_scraper(source: str):
    if source == "suumo":
        return SuumoScraper()
    elif source == "mansion_review":
        return MansionReviewScraper()
    else:
        raise ValueError(f"Unknown source: {source}")
