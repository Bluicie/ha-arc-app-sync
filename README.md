# Arc Launcher App Sync for Home Assistant

Keep the apps on your Android/Google TVs in step: one **leader** TV decides which apps the others have.
Apps the leader has are copied to the other TVs over ADB; apps the leader doesn't have are removed there.
A kids profile limits a TV to an allowlist instead.

This is an add-on to the [Arc Launcher integration](https://github.com/Bluicie/ha-arc-launcher): it uses the TVs
you set up there and puts its sensors on the same devices. If you don't want app sync, just don't install it.

## How it works

- **Copying apps:** the APK files (with all splits) are pulled from the leader and installed on the other TV with
  the Play Store as installer, so the app keeps getting updates. If that fails (for example an older Android
  version or a different CPU), the app's Play Store page is opened on that TV once, so someone can press Install.
- **Profiles per TV:**
  - **Full:** gets every user-installed app of the leader plus the must-have apps (when the leader has them in any
    form, also as a system app). User-installed apps the leader doesn't have are removed.
  - **Kids:** gets only the leader's apps that are on the kids allowlist. Every other user-installed app is removed.
  - **Off:** a TV in neither list is left alone.
- **Never removed:** system apps, must-have apps, Arc Launcher (`com.omeda.arc`, `com.bluicie.arc`) and
  Projectivy (`com.spocky.projengmenu`).
- **Safety:** nothing happens when the leader can't be reached or reports no apps. When a TV would lose more apps
  in one run than the limit (default 5), nothing is removed there and the TV shows *Needs attention*.
- **Dry run** is on after setup: a run only reports what it would change. Check the sensors, then turn the
  *Dry run* switch off.
- A run happens every day at the time you choose, or when you press **Sync apps now**. TVs that are asleep or
  unreachable are skipped and reported; they keep what the last run found.

## Requirements

- The [Arc Launcher integration](https://github.com/Bluicie/ha-arc-launcher) with your TVs set up.
- On every TV: developer options with **network debugging** (ADB over the network, port 5555) turned on.
- Home Assistant 2025.6 or newer.

## Installation

1. In HACS, open the menu > **Custom repositories**, add `https://github.com/Bluicie/ha-arc-app-sync` as type
   **Integration**, and install **Arc Launcher App Sync**.
2. Restart Home Assistant.
3. **Settings > Devices & services > Add integration > Arc Launcher App Sync.**

## Allowing Home Assistant on the TVs

Home Assistant makes its own ADB key the first time it needs one (kept in `.storage/arc_app_sync/`). The first time
it connects to a TV, the TV asks **"Allow USB debugging?"**: tick **Always allow from this computer** and choose
**Allow**. Do this once on every TV; the setup's app step and the first run (press **Sync apps now**) trigger the
question. A TV that never got the question in time shows *Unreachable* with the reason in its `problems`
attribute; press **Sync apps now** again while you're at the TV.

## Setup

1. **Leader:** *Automatic* uses the TV the other TVs follow in Arc Launcher (or the one that shares its layout),
   and moves along when that changes. You can also pick a TV.
2. **Profile per TV:** put each other TV under *Full* or *Kids*, or in neither to leave it alone.
3. **Apps and schedule:** the must-have apps and kids allowlist offer the leader's user-installed apps; type a
   package name (such as `com.netflix.ninja`) to add an app the list doesn't show. Then the most removals per run,
   the daily sync time and dry run.

Change any of it later with **Configure**.

## Entities

On each TV's Arc Launcher device:

| Entity | What it shows |
|---|---|
| Apps missing | Apps the TV should get; attributes `packages`, `needs_play_store` (waiting for Install in the Play Store), `installed` (last run) |
| Apps to remove | Apps the TV should lose; attributes `packages`, `removed` (last run) |
| Last app sync | When the TV was last checked |
| App sync status | `never`, `ok`, `dry_run`, `attention`, `asleep`, `unreachable` or `leader_unavailable`; attribute `problems` |

On the *Arc App Sync* service device: **Sync apps now** (button) and **Dry run** (switch).

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
git clone --depth 1 --branch v0.2.0 https://github.com/Bluicie/ha-arc-launcher /tmp/arc
cp -r /tmp/arc/custom_components/arc_launcher custom_components/
.venv/bin/pytest
```

ADB is mocked in the tests.

## License

MIT
