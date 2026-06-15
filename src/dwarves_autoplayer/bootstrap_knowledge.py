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
    Source("advanced_professions", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Advanced_Professions", "wiki"),
    Source("formations", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Formations", "wiki"),
    Source("gear", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Gear", "wiki"),
    Source("sets", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Sets", "wiki"),
    Source("stats", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Stats", "wiki"),
    Source("shop", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Shop", "wiki"),
    Source("leveling", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Leveling", "wiki"),
    Source("ultimates", "https://dwarves-glory-death-and-loot.fandom.com/wiki/Ultimates", "wiki"),
    Source("steam_stumbling_blocks", "https://steamcommunity.com/sharedfiles/filedetails/?id=3449234832", "guide"),
    Source("steam_hints", "https://steamcommunity.com/sharedfiles/filedetails/?id=3125186427", "guide"),
    Source("steam_improve_dwarfs", "https://steamcommunity.com/app/2205850/discussions/0/595142432657552462/", "discussion"),
    Source("steam_my_build", "https://steamcommunity.com/app/2205850/discussions/0/604149834549640548/", "discussion"),
    Source("steam_advanced_class_items", "https://steamcommunity.com/app/2205850/discussions/0/4852155152090217800/", "discussion"),
    Source("steam_immortal_build", "https://steamcommunity.com/app/2205850/discussions/0/760681630846210215/", "discussion"),
    Source("crazygames_how_to_play", "https://www.crazygames.com/game/dwarves-glory-death-and-loot", "guide"),
    Source("thegamer_beginner_tips", "https://www.thegamer.com/dwarves-glory-death-and-loot-best-beginner-starting-tips/", "guide"),
    Source("thegamer_professions", "https://www.thegamer.com/dwarves-glory-death-and-loot-complete-guide-what-are-professions/", "guide"),
    Source("thegamer_formations", "https://www.thegamer.com/dwarves-glory-death-and-loot-complete-guide-every-formation-how-to-unlock/", "guide"),
    Source("sets_tier_list", "https://powerupgaming.co.uk/2026/01/26/dwarves-glory-death-and-loot-tier-list-best-sets-ranked/", "guide"),
    Source("reddit_fire_mage_build", "https://old.reddit.com/r/DwarvesTheGame/comments/1k87d6c/another_build_that_works_well/", "reddit"),
    Source("reddit_beginner_guide", "https://old.reddit.com/r/DwarvesTheGame/comments/1jj3f38/new_beginner_guide_droped_quite_useful_xd/", "reddit"),
    Source("reddit_best_sets", "https://old.reddit.com/r/DwarvesTheGame/comments/1qrguf0/best_sets/", "reddit"),
    Source("reddit_new_player_questions", "https://old.reddit.com/r/DwarvesTheGame/comments/1qq1rku/help_me_enjoy_the_game_to_the_fullest_questions/", "reddit"),
    Source("reddit_gem_farming", "https://old.reddit.com/r/DwarvesTheGame/comments/1r7c4x0/gem_farming_strategy_up_to_168_gems_per_30_seconds/", "reddit"),
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
    source_kind_counts: dict[str, int] = {}
    for page in pages:
        source_kind_counts[page["kind"]] = source_kind_counts.get(page["kind"], 0) + 1

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "purpose": "Seed knowledge for local screen-based Dwarves autoplayer decisions.",
        "sources": [{"name": page["name"], "url": page["url"], "title": page["title"]} for page in pages],
        "source_coverage": source_kind_counts,
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
        "strategy_model": {
            "early_game": [
                "Prioritize getting enough dwarves and weapons online before obsessing over random loot.",
                "Push battles quickly when fights are easy; dying or resetting can still advance long-term progress.",
                "Use the battle selection screen to choose manageable fights and keep the run loop moving.",
                "Storage/inventory space matters because holding useful set pieces enables later upgrades.",
            ],
            "team_baseline": [
                "Use durable frontline dwarves to protect damage dealers.",
                "Maintain sustain through Priests or Supporters when fights start lasting longer.",
                "Add crowd control or area damage as waves become denser.",
                "Avoid spreading permanent upgrades too thin early; commit to a coherent damage/sustain plan.",
            ],
            "shopping": [
                "Buy/equip weapons that define useful professions before buying low-synergy extras.",
                "Prefer upgrades, set pieces, and role-defining items over random sidegrades.",
                "Reroll when no useful buy/equip/upgrade action is available and gold allows it.",
                "Advanced-profession set items and high-tier drops become relevant after shop progression.",
            ],
            "runes_and_talents": [
                "Spend skill/rune points toward the current team plan instead of sprinkling points everywhere.",
                "Target class-specific rune bonuses when a build leans heavily into one role.",
                "Mage/fire builds, healer sustain builds, and formation-based comps all need matching runes.",
            ],
            "automation_translation": [
                "When in doubt, choose actions that advance the battle loop: battle select, fight, next, continue, retry.",
                "Avoid destructive actions such as retire, sell, reset, delete, or new clan unless explicitly planned.",
                "If the bot can read or infer choices, favor battle progress over idle menu exploration.",
                "Use video-derived state recognition for where to click; use wiki/guide baseline for what to prioritize once OCR exists.",
            ],
        },
        "professions": {
            "frontline": ["Knight", "Warrior"],
            "damage": ["Warrior", "Mage", "Archer", "Thief"],
            "support": ["Priest", "Supporter"],
            "advanced_targets": ["Paladin", "Warpriest", "Warlock", "Reaper", "Cannoneer", "Beastmaster"],
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
            "role_targets": {
                "tank": ["Golden", "Umbra"],
                "healer": ["Djinn", "Druid", "Divine"],
                "warrior": ["Executioner", "Titan", "Dwarven"],
                "mage": ["Dragon", "Storm", "Frost"],
                "thief": ["White Reaver", "Assassin", "Crescent"],
                "supporter": ["Centurion"],
            },
            "notes": [
                "Prioritize complete set synergies over isolated low-impact pieces.",
                "Executioner and Golden are useful baseline targets for early carry/tank logic.",
                "Djinn/other healer sets are strong sustain targets when the team starts losing longer fights.",
            ],
        },
        "known_build_archetypes": {
            "balanced_core": [
                "frontline tank",
                "physical or magical damage carry",
                "healer/support sustain",
                "secondary crowd control or area damage",
            ],
            "mage_fire_core": [
                "multiple mages",
                "mana regeneration",
                "fire damage/rage/hope style runes",
                "intelligence and magic penetration gear",
            ],
            "sustain_core": [
                "Golden or other durable tank setup",
                "Djinn/healer sustain",
                "support banner utility",
                "damage carry protected by formation and healing",
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
