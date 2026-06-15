from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml
from bs4 import BeautifulSoup


ROOT = Path.cwd()
KNOWLEDGE_DIR = ROOT / "knowledge"
RAW_DIR = KNOWLEDGE_DIR / "raw"
IMAGE_DIR = KNOWLEDGE_DIR / "images"
BASELINE_PATH = KNOWLEDGE_DIR / "baseline.yaml"

USER_AGENT = "dwarves-autoplayer-knowledge-bootstrap/0.1 (+local personal research)"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    kind: str


SOURCES = [
    Source("wiki_home", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Dwarves:_Glory,_Death_and_Loot_Wiki", "wiki"),
    Source("professions", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Professions", "wiki"),
    Source("formations", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Formations", "wiki"),
    Source("stats", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Stats", "wiki"),
    Source("shop", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Shop", "wiki"),
    Source("leveling", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Leveling", "wiki"),
    Source("ultimates", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Ultimates", "wiki"),
    Source("steam_stumbling_blocks", "https://steamcommunity.com/sharedfiles/filedetails/?id=3449234832", "guide"),
    Source("steam_hints", "https://steamcommunity.com/sharedfiles/filedetails/?id=3125186427", "guide"),
    Source("sets_tier_list", "https://powerupgaming.co.uk/2026/01/26/dwarves-glory-death-and-loot-tier-list-best-sets-ranked/", "guide"),
]


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def session() -> requests.Session:
    client = requests.Session()
    client.headers.update({"User-Agent": USER_AGENT})
    return client


def fetch_text(client: requests.Session, source: Source) -> str:
    if source.kind == "wiki":
        title = source.url.rsplit("/wiki/", 1)[-1].replace("_", " ")
        response = client.get(
            "https://dwarves-glory-death-and-loot.fandom.com/api.php",
            params={"action": "parse", "format": "json", "page": title, "prop": "text"},
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
        html = data.get("parse", {}).get("text", {}).get("*")
        if not html:
            raise requests.RequestException(f"Wiki API returned no parse text for {title}")
        return html

    response = client.get(source.url, timeout=25)
    response.raise_for_status()
    return response.text


def extract_page(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title = soup.find(["h1", "title"])
    title_text = clean_text(title.get_text(" ")) if title else url
    body = soup.find("main") or soup.find("article") or soup.find(class_="mw-parser-output") or soup.body or soup

    headings: list[str] = []
    paragraphs: list[str] = []
    bullets: list[str] = []
    images: list[str] = []

    for heading in body.find_all(["h1", "h2", "h3"]):
        text = clean_text(heading.get_text(" "))
        if text and text not in headings:
            headings.append(text)

    for paragraph in body.find_all("p"):
        text = clean_text(paragraph.get_text(" "))
        if len(text) >= 40:
            paragraphs.append(text)

    for item in body.find_all("li"):
        text = clean_text(item.get_text(" "))
        if 12 <= len(text) <= 240:
            bullets.append(text)

    for image in body.find_all("img"):
        src = image.get("src") or image.get("data-src")
        if src and (("static.wikia" in src) or ("steamusercontent" in src) or ("static.wikia.nocookie.net" in src)):
            if src.startswith("//"):
                src = f"https:{src}"
            images.append(src)

    return {
        "url": url,
        "title": title_text,
        "headings": headings[:80],
        "paragraphs": paragraphs[:80],
        "bullets": bullets[:200],
        "images": list(dict.fromkeys(images))[:60],
    }


def clean_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)


def download_images(client: requests.Session, page: dict[str, Any], source_name: str) -> list[str]:
    saved: list[str] = []
    for index, url in enumerate(page.get("images", []), start=1):
        try:
            parsed = urlparse(url)
            ext = Path(parsed.path).suffix.lower()
            if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
                ext = ".jpg"
            out_path = IMAGE_DIR / source_name / f"{index:03d}{ext}"
            if out_path.exists():
                saved.append(str(out_path.relative_to(ROOT)))
                continue

            response = client.get(url, timeout=25)
            response.raise_for_status()
            if not response.headers.get("content-type", "").startswith("image/"):
                continue

            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(response.content)
            saved.append(str(out_path.relative_to(ROOT)))
            time.sleep(0.2)
        except requests.RequestException:
            continue

    return saved


def build_baseline(pages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "purpose": "Seed knowledge for local screen-based Dwarves autoplayer decisions.",
        "sources": [{"name": page["name"], "url": page["url"], "title": page["title"]} for page in pages],
        "game_model": {
            "loop": [
                "start run or fight",
                "survive auto battles",
                "collect rewards",
                "buy or upgrade useful gear",
                "improve clan/runes/talents between runs",
                "retry after defeat",
            ],
            "important_screens": ["main menu", "start menu", "battle", "reward", "shop", "rune/talent menu", "defeat"],
        },
        "professions": {
            "frontline": ["Knight", "Warrior"],
            "damage": ["Warrior", "Mage", "Archer", "Thief"],
            "support": ["Priest", "Supporter"],
            "baseline_priority": [
                "Keep durable frontliners alive.",
                "Prefer healing/support pieces when sustain is weak.",
                "Add crowd control and AoE damage as waves get harder.",
            ],
        },
        "formation_rules": [
            "Winning battles with lineup requirements unlocks formations.",
            "Three or more of a profession can unlock profession formations.",
            "Supporter-heavy Bannerlords can add strong healing based on Supporter max health.",
        ],
        "stats_rules": [
            "Base stats come from the dwarf as bought.",
            "Growth comes from profession levels and artifacts.",
            "Items provide gear stats.",
            "Special stats come from skill tree/rune effects and artifact side effects.",
        ],
        "item_set_priorities": {
            "s_tier": ["Djinn", "Golden", "Executioner", "Dragon", "White Reaver", "Umbra"],
            "a_tier": ["Dwarven", "Holy Authority", "Boar", "Crimson", "Night", "Titan", "Holy Smite"],
            "notes": [
                "Prioritize complete set synergies over isolated low-impact pieces.",
                "Executioner and Golden are useful baseline targets for early carry/tank logic.",
            ],
        },
        "ui_priorities": {
            "high": ["start", "fight", "continue", "claim", "retry", "ok", "confirm", "upgrade", "buy", "equip"],
            "medium": ["reroll", "shop", "rune", "talent", "formation", "daily"],
            "avoid": ["delete", "sell", "retire", "reset", "new clan"],
        },
        "autoplayer_policy": {
            "safe_default": "Click high-priority progress buttons first, avoid destructive labels, then explore unknown buttons.",
            "shop_default": "Prefer upgrades/equips/buys, then reroll only when no useful purchase is found.",
            "learning_default": "Save screenshots and crops, record clicks that change screens, and down-rank clicks that do nothing.",
        },
    }


def main() -> None:
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    client = session()
    pages: list[dict[str, Any]] = []
    for source in SOURCES:
        print(f"Fetching {source.name}: {source.url}")
        try:
            html = fetch_text(client, source)
            page = extract_page(html, source.url)
            page["name"] = source.name
            page["kind"] = source.kind
            page["downloaded_images"] = download_images(client, page, source.name)
            save_json(RAW_DIR / f"{source.name}.json", page)
            pages.append(page)
            time.sleep(0.5)
        except requests.RequestException as exc:
            print(f"  failed: {exc}")

    baseline = build_baseline(pages)
    with BASELINE_PATH.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(baseline, handle, sort_keys=False, allow_unicode=True)

    print(f"\nWrote {BASELINE_PATH}")
    print(f"Cached {len(pages)} source pages and image folders under {KNOWLEDGE_DIR}")


if __name__ == "__main__":
    main()
