# Dwarves Autoplayer

Local Windows screen automation for **Dwarves: Glory, Death and Loot** on Steam.

This is for personal single-player automation, accessibility, and experimentation. It does not bypass anti-cheat, patch the game, read memory, inject code, or hide itself.

## What It Does

- Watches the game window using screenshots.
- Finds buttons/screens using image templates you capture from your own game.
- Clicks through a run, shops/rewards, death/retry, and starts the next run.
- Logs what it sees and does.
- Has a visible hotkey stop and a mouse failsafe.

## Setup

1. Close the game or leave it at the main menu.
2. Run setup. This creates a local `.venv` inside the project and installs the bot there:

```powershell
cd "E:\Projects\dwarves-autoplayer"
.\setup.bat
```

3. Start the game in Steam.
4. Use windowed or borderless windowed mode if possible. Keep scaling at 100% while you teach templates.

5. Optional but recommended before autonomous play:

```powershell
.\run_bootstrap_knowledge.bat
```

This caches public wiki/guide extracts and images into `knowledge\` and writes `knowledge\baseline.yaml`.

## Teach The Bot

The bot needs small screenshots of buttons or labels. Capture clean snippets, not the whole screen.

Run:

```powershell
.\capture_template.bat
```

Recommended template names:

- `retry`
- `defeat`
- `start`
- `fight`
- `continue`
- `claim`
- `shop`
- `reroll`
- `buy`
- `confirm`
- `ok`

For each template:

1. Type the template name.
2. Move mouse to the top-left of the button/label and press Enter.
3. Move mouse to the bottom-right and press Enter.

The image is saved into `templates\`.

## Run

For hands-off exploration, use:

```powershell
.\run_autonomous.bat
```

This starts immediately. It captures screenshots, fingerprints repeated screens, detects button-like UI regions, tries clicks, and records which clicks changed the screen. Its learning state is saved in `learning_data\`.

If `knowledge\baseline.yaml` is missing, autonomous mode bootstraps it first from public wiki/guide sources.

For the older template-first mode, use:

```powershell
.\run_bot.bat
```

Hotkeys in either mode:

- `Ctrl+Alt+S`: start/pause
- `Ctrl+Alt+Q`: quit
- Move mouse to the top-left corner of the screen to trigger PyAutoGUI failsafe.

To tune shop coordinates, run:

```powershell
.\print_mouse.bat
```

Point at a buy button and read the `window=(x,y)` values in the console, then put those values in `config.yaml`.

## Strategy

The default strategy is deliberately simple:

1. If death/retry is visible, click retry.
2. If claim/continue/ok/confirm is visible, click it.
3. If shop is visible, buy from configured slots, optionally reroll, then start the next fight.
4. If start/fight is visible, click it.
5. If nothing is recognized and autonomous learning is enabled, try the most promising button-like region and remember whether the screen changed.
6. If nothing is clickable, wait and scan again.

Edit `config.yaml` to change priorities, click slots, delays, and confidence thresholds.

## Autonomous Learning

Autonomous mode now uses a deterministic state playbook first. It identifies the current screen and uses a specific action plan:

- `main_hall`: open battle selection
- `shop_menu`: return to the battle tab/selection loop
- `battle_select`: choose a visible battle card
- `battle_running`: wait and keep battle speed high
- `battle_report`: advance back toward the hall/rewards loop

The old free-click explorer is disabled by default and should only be used for debugging.

It creates:

- `learning_data\screenshots\`: periodic game screenshots
- `learning_data\templates\`: crops of clicked UI candidates
- `learning_data\state.json`: remembered screens, candidates, attempts, and successes

If the bot stalls, run:

```powershell
.\diagnose_latest.bat
```

It prints the detected state and planned click for the latest captured screenshot.

## Tutorial Video Training

Put tutorial or playthrough videos in `learning_data\videos\`. To process `tutorial1.mp4`:

```powershell
.\train_tutorial_video.bat
```

This samples the video, classifies frames with the state playbook, saves representative frames, and writes:

- `learning_data\video_training\tutorial1\timeline.csv`
- `learning_data\video_training\tutorial1\summary.json`
- `knowledge\video_baseline.yaml`

## Project Layout

- `src\dwarves_autoplayer\bot.py`: main autoplayer loop
- `src\dwarves_autoplayer\playbook.py`: deterministic screen classifier and action playbook
- `src\dwarves_autoplayer\train_from_video.py`: offline video sampler for tutorial/playthrough footage
- `src\dwarves_autoplayer\learner.py`: screenshot capture and autonomous click learner
- `src\dwarves_autoplayer\bootstrap_knowledge.py`: wiki/guide baseline bootstrapper
- `knowledge\baseline.yaml`: generated strategy and source baseline
- `src\dwarves_autoplayer\capture_template.py`: template capture helper
- `config.yaml`: strategy and matching configuration
- `templates\`: your local button/label screenshots
- `pyproject.toml`: Python package metadata and dependencies

## Notes

- Capture templates at the same game resolution and UI scale you plan to run.
- If the bot clicks slightly off, recapture smaller, cleaner templates.
- If it does nothing, lower `match_threshold` a little, for example `0.82`.
- If it clicks wrong things, raise `match_threshold`, for example `0.92`.
