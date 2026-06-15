from __future__ import annotations

from collections import Counter

from dwarves_autoplayer.baseline import load_baseline


def main() -> None:
    baseline = load_baseline()
    if not baseline:
        raise SystemExit("No knowledge/baseline.yaml found. Run run_bootstrap_knowledge.bat first.")

    sources = baseline.get("sources", [])
    coverage = baseline.get("source_coverage", {})
    print(f"Sources: {len(sources)}")
    for kind, count in coverage.items():
        print(f"  {kind}: {count}")

    print("\nStrategy baseline:")
    strategy = baseline.get("strategy_model", {})
    for section in ("early_game", "team_baseline", "shopping", "runes_and_talents", "automation_translation"):
        print(f"\n{section}:")
        for item in strategy.get(section, []):
            print(f"  - {item}")

    print("\nSet targets:")
    sets = baseline.get("item_set_priorities", {})
    for tier in ("s_tier", "a_tier"):
        values = sets.get(tier, [])
        print(f"  {tier}: {', '.join(values)}")

    source_domains = Counter(source["url"].split("/")[2] for source in sources if "://" in source["url"])
    print("\nSource domains:")
    for domain, count in source_domains.most_common():
        print(f"  {domain}: {count}")


if __name__ == "__main__":
    main()

