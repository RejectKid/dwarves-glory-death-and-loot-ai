# Dwarves Autoplayer

Local Windows screen automation for **Dwarves: Glory, Death and Loot** on Steam.

This is for personal single-player automation, accessibility, and experimentation. It does not bypass anti-cheat, patch the game, read memory, inject code, or hide itself.

## What It Does

- Watches the game window using screenshots.
- Classifies screens with a deterministic state playbook.
- Uses wiki/guide/Reddit/Steam/video baselines to choose a progress-first strategy.
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

## Run

```powershell
.\run_autonomous.bat
```

Hotkeys:

- `Ctrl+Alt+S`: start/pause
- `Ctrl+Alt+Q`: quit
- Move mouse to the top-left corner of the screen to trigger PyAutoGUI failsafe.

## Strategy

The runtime bot is now a state machine:

- `main_hall`: open battle selection
- `shop_menu`: return to the battle tab/selection loop
- `battle_select`: choose a visible battle card, rotating choices if stuck
- `battle_running`: wait and keep battle speed high
- `battle_report`: advance back toward the hall/rewards loop

It also runs an economy cycle through the bottom hotbar so the run does not only fight:

- `3`: tavern
- `4`: storage
- `5`: forge
- `6`: main hall
- `7`: recruit dwarves
- `8`: loot
- `9`: battle
- `0`: raid probe

The menu positions are ratios in `config.yaml` under `strategy.bottom_menu`. The first version uses broad, safe clicks in those menus because OCR is not installed yet; the next upgrade should read menu text and item/unit names before buying or upgrading.

The knowledge baseline currently informs the bot at the policy level: favor battle-loop progress, avoid destructive menus, keep fights moving, and treat shopping/build strategy as a next OCR-driven upgrade. The bot logs how many sources and video samples it loaded at startup.

## Diagnose

If the bot stalls:

```powershell
.\diagnose_latest.bat
```

That prints the latest screenshot's detected state and planned click. Runtime screenshots and timeline data are saved under:

```text
learning_data\screenshots\
learning_data\runtime_timeline.csv
```

## Project Layout

- `src\dwarves_autoplayer\bot.py`: main autoplayer loop
- `src\dwarves_autoplayer\playbook.py`: screen classifier and action playbook
- `src\dwarves_autoplayer\strategy.py`: knowledge-backed runtime strategy
- `src\dwarves_autoplayer\recorder.py`: screenshots and runtime timeline
- `src\dwarves_autoplayer\bootstrap_knowledge.py`: internet/wiki/Reddit baseline bootstrapper
- `src\dwarves_autoplayer\train_from_video.py`: offline tutorial video sampler
- `knowledge\baseline.yaml`: generated strategy/source baseline
- `knowledge\video_baseline.yaml`: generated video-state baseline
