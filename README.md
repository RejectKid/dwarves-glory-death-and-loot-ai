# Dwarves Autoplayer

Local Windows screen automation for **Dwarves: Glory, Death and Loot** on Steam.

This is for personal single-player automation, accessibility, and experimentation. It does not bypass anti-cheat, patch the game, read memory, inject code, or hide itself.

## What It Does

- Watches the game window using screenshots.
- Classifies screens with a deterministic state playbook.
- Uses wiki/guide/Reddit/Steam/video baselines to choose a progress-first strategy.
- Records human teaching sessions with screenshots, clicks, OCR text, and before/after states.
- Trains a learned click policy from those demonstrations.
- Uses learned high-confidence human examples before falling back to any hand-written automation.
- Clicks through the core loop: main hall, battle selection, battle, battle report, and shop/menu recovery.
- Records screenshots and a runtime timeline for diagnosis.

## Setup

```powershell
cd "E:\Projects\dwarves-autoplayer"
.\setup.bat
```

Start the game in Steam and use windowed or borderless windowed mode.

## Refresh Knowledge

Pull public wiki, guide, Steam, Reddit, and strategy-source data:

```powershell
.\run_bootstrap_knowledge.bat
```

Inspect the strategy baseline:

```powershell
.\knowledge_report.bat
```

Process all local tutorial/playthrough videos in `learning_data\videos\`:

```powershell
.\train_tutorial_video.bat
```

The repository does not include the large video files. For the current checked-in video baseline, these YouTube videos were saved locally before training:

- [Dwarves video 1](https://www.youtube.com/watch?v=dKzTFycfKw8)
- [Dwarves video 2](https://www.youtube.com/watch?v=hLhocQB0wNs)
- [Dwarves video 3](https://www.youtube.com/watch?v=HpNRjpKWgyM)

Save downloaded/provided `.mp4` files here:

```text
learning_data\videos\
```

Example local filenames used during training:

```text
Tips.mp4
tutorial1.mp4
tutorial2.mp4
```

Video training writes:

- `learning_data\video_training\<video-name>\timeline.csv`
- `learning_data\video_training\<video-name>\summary.json`
- `knowledge\video_baseline.yaml`

After cloning the repo, rerun knowledge and video training after adding local videos:

```powershell
.\run_bootstrap_knowledge.bat
.\train_tutorial_video.bat
```

## Teach, Train, Run

This project now works best as an imitation-learning loop. The old macro autoplayer is intentionally disabled by default because it was too willing to click through menus without understanding the screen.

First, teach it by playing normally:

```powershell
.\teach_mode.bat
```

While teach mode is running:

- play the game yourself
- hover/read items and make the decisions you want the bot to copy
- use `Ctrl+Alt+S` to pause/resume recording
- use `Ctrl+Alt+Q` to finish the session

Teach mode writes sessions here:

```text
learning_data\demonstrations\<session-id>\
```

Each session contains:

- before/after screenshots for your clicks
- screen state before and after the click
- click position as window ratios
- OCR text when Tesseract is available
- hover/tooltip crops when your mouse rests over an item
- optional teaching labels from hotkeys
- periodic sample screenshots

Teaching label hotkeys:

- `Ctrl+Alt+1`: good choice
- `Ctrl+Alt+2`: bad choice
- `Ctrl+Alt+3`: comparing tooltip
- `Ctrl+Alt+4`: equip gear
- `Ctrl+Alt+5`: place relic
- `Ctrl+Alt+6`: skip item

Then train the learned policy:

```powershell
.\train_demonstrations.bat
```

That writes:

```text
knowledge\learned_policy.yaml
```

Then run autoplay:

```powershell
.\run_autonomous.bat
```

At runtime, the bot fingerprints the current screenshot, looks for similar screens in `knowledge\learned_policy.yaml`, and clicks where you clicked when confidence is high. If it cannot find a confident learned action, it avoids the old economy macro path by default.

Hotkeys:

- `Ctrl+Alt+S`: start/pause
- `Ctrl+Alt+Q`: quit
- Move mouse to the top-left corner of the screen to trigger PyAutoGUI failsafe.

## Strategy

The runtime bot is now a hybrid:

- learned demonstration policy first
- deterministic battle/report helpers second
- optional hand-written economy macro only if `strategy.economy_cycle_enabled` is set back to `true`

The deterministic state machine still recognizes:

- `main_hall`: open battle selection
- `tavern`
- `storage`
- `forge`
- `recruit_dwarves`
- `loot`
- `shop_menu`: return to the battle tab/selection loop
- `battle_select`: choose a visible battle card, rotating choices if stuck
- `battle_running`: wait and keep battle speed high
- `battle_report`: advance back toward the hall/rewards loop
- `raid`
- `defeat`
- `unknown`

The perception layer produces structured observations with:

- screenshot fingerprint
- visual state hint
- OCR-refined state when text is readable
- visible keywords like buy, equip, reroll, remove, relic, artifact, and set
- configured regions for bottom menu, inventory slots, dwarf cards, relic slots, battle cards, and resources

The old economy cycle is still present but disabled by default. If you turn `strategy.economy_cycle_enabled` back on, it cycles through the bottom hotbar:

- `3`: tavern
- `4`: storage
- `5`: forge
- `6`: main hall
- `7`: recruit dwarves
- `8`: loot
- `9`: battle
- `0`: raid probe

The menu positions are ratios in `config.yaml` under `strategy.bottom_menu`. The first version uses broad, safe clicks in those menus because OCR is not installed yet; the next upgrade should read menu text and item/unit names before buying or upgrading.

Gear and relic/artifact equipping in the hand-written fallback is conservative now. After visiting storage/loot, the bot goes to `6` Main Hall and inspects visible inventory slots. It does not blindly walk down the row. For each slot, it hovers, reads the tooltip with OCR, classifies the item as gear or relic/artifact, scores it against the current build plan, and only equips it if it clears `strategy.min_equip_score`.

Gear is placed by clicking the item and then clicking the target dwarf card. Relics/artifacts are placed by clicking the item and then clicking one of the two relic boxes below the selected dwarf.

Tune drop targets in `config.yaml`:

```yaml
strategy:
  equip_method: "click_pair"
  min_equip_score: 2.0
  dwarf_roles:
  equip_targets:
  relic_targets:
  inventory_slots:
```

There are gear target entries for up to 10 dwarves and two relic target boxes per dwarf. `dwarf_roles` controls who receives tank, carry, healer, support, magic, or flex items first. If OCR cannot read a tooltip, smart equip skips the slot instead of risking a bad click.

The knowledge baseline currently informs the bot at the policy level: favor battle-loop progress, avoid destructive menus, keep fights moving, and treat shopping/build strategy as a next OCR-driven upgrade. The bot logs how many sources and video samples it loaded at startup.

Before every click, the bot now creates a strategy decision with:

- goal
- rationale
- risks
- build priorities
- roster and gear/set guidance
- source basis from wiki/guide/Reddit/Steam/video training

Those decisions are written to `bot.log`, and the runtime timeline includes each action goal.

The bot also pauses before acting. Economy, recruit, equip, forge, storage, and drag actions get longer deliberation time than battle/report actions. Tune this in `config.yaml` under:

```yaml
deliberation:
tooltip_reader:
```

The bot also maintains a lightweight memory file:

```text
learning_data\game_memory.json
```

Today that memory provides the structure for roster, unit roles, gear seen, relics/artifacts seen, equipped sets, and chosen build archetype. Each dwarf can eventually be modeled with gear plus two relic/artifact slots. Until OCR is added, those fields are mostly scaffolding and broad guidance; once OCR can read unit/item text, this is where the bot will learn which dwarves, set pieces, relics, and upgrades are actually working.

The stronger learning path is demonstration data. The bot needs examples of you:

- choosing battles
- recruiting dwarves
- buying/rerolling/skipping loot
- comparing tooltips
- equipping gear onto dwarf cards
- placing relics/artifacts into the two boxes below each dwarf
- recovering after losses and restarting runs

More varied teaching sessions produce better policy matches.

Inspect memory and current build targets with:

```powershell
.\memory_report.bat
```

Most game items and menus expose useful tooltip text. The bot now hovers before risky recruit/loot/storage/forge clicks, saves tooltip crops under `learning_data\tooltips\`, and uses OCR when available.

Python installs `pytesseract`, but Windows also needs the Tesseract OCR application installed separately for text extraction. If Tesseract is missing, the bot still saves tooltip images and logs that OCR is unavailable.

Install Tesseract on Windows and make sure `tesseract.exe` is on `PATH`. Common install options include the UB Mannheim Windows build or a package manager install. After installing, restart PowerShell and verify:

```powershell
tesseract --version
```

## Diagnose

If the bot stalls:

```powershell
.\diagnose_latest.bat
```

That prints the latest screenshot's detected state, OCR availability, visible keywords, learned-policy status, matched training example, planned click, confidence, and rationale. Runtime screenshots and timeline data are saved under:

```text
learning_data\screenshots\
learning_data\runtime_timeline.csv
```

## Project Layout

- `src\dwarves_autoplayer\bot.py`: main autoplayer loop
- `src\dwarves_autoplayer\teach_mode.py`: human demonstration recorder
- `src\dwarves_autoplayer\train_from_demonstrations.py`: trains `knowledge\learned_policy.yaml`
- `src\dwarves_autoplayer\learned_policy.py`: runtime imitation policy
- `src\dwarves_autoplayer\perception.py`: structured screenshot/OCR observation layer
- `src\dwarves_autoplayer\playbook.py`: screen classifier and action playbook
- `src\dwarves_autoplayer\strategy.py`: knowledge-backed runtime strategy
- `src\dwarves_autoplayer\recorder.py`: screenshots and runtime timeline
- `src\dwarves_autoplayer\bootstrap_knowledge.py`: internet/wiki/Reddit baseline bootstrapper
- `src\dwarves_autoplayer\train_from_video.py`: offline tutorial video sampler
- `knowledge\baseline.yaml`: generated strategy/source baseline
- `knowledge\video_baseline.yaml`: generated video-state baseline
