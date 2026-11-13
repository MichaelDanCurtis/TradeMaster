# Install TradeMaster for Mac

Download the Apple Silicon `.dmg` from the
[GitHub releases page](https://github.com/MichaelDanCurtis/TradeMaster/releases).
Open it, drag **TradeMaster.app** into **Applications**, then open TradeMaster.

This preview requires **macOS 13 or newer on an Apple Silicon Mac**. Python, Node,
the dashboard, API and background workers are bundled. No Terminal, Homebrew,
source checkout or dependency download is required to launch the application.
Intel Mac and Windows installers are not included in this release.

## First launch

The app opens the market workstation in its own window. Configure your own
Alpaca and research providers in **Settings**. Codex subscription research still
requires a separately installed, signed-in Codex CLI. Model weights, optional
forecast environments, Docker/LEAN and provider accounts are not bundled.

The distributed package contains no account database, credentials or research
history. It does not automatically import a source checkout's settings or data.
It starts with fresh local settings; the existing source checkout is unaffected.

The app starts its API on `127.0.0.1:18897` and dashboard on
`127.0.0.1:18898`. It starts the research, deployment and paper schedule workers
and checks their heartbeats before showing the dashboard. Workers act only on
work explicitly queued/approved through the product. It refuses to start if its
ports are occupied and does not adopt or stop another application's services.
Quit TradeMaster to stop its services. Paper schedules do not run while the app
is closed. **View → Open in Browser** opens the same local instance.

## Signing status

The first preview is signed with the maintainer's Developer ID Application
certificate. Check the release notes for Apple notarization status. A signed but
not notarized preview may require **System Settings → Privacy & Security → Open
Anyway** after attempting to open it. Do not disable Gatekeeper globally. If your
Mac is managed, its administrator may prohibit unnotarized apps.

## Your data and updates

The app keeps its SQLite database, private artifacts and logs in:

`~/Library/Application Support/TradeMaster/`

Secrets entered through Settings use the existing credential-store behavior,
including the macOS Keychain. **TradeMaster → Open Logs** opens the diagnostic
folder. Replacing the app bundle does not remove this data. Quit the app before
copying a newer version into Applications or backing up its data folder.

There is no automatic updater in this preview. Download future releases from the
same GitHub repository. Deleting the app does not delete account data; remove the
Application Support folder separately only when you intentionally want to reset it.

## Build from source

On an Apple Silicon Mac with Xcode command-line tools, Node 22, uv and Python 3.12:

```sh
npm ci
uv sync --frozen --extra dev
python3 scripts/build-macos.py --version 0.1.0
```

The default build uses an ad-hoc signature for local testing. To produce a
Developer ID signed build, provide your own installed signing identity:

```sh
python3 scripts/build-macos.py --version 0.1.0 --identity 'Developer ID Application: Your Name (TEAMID)'
```

Outputs appear in `.release/`. The build exports hash-locked Python dependencies
into a clean runtime, builds the dashboard in `.next-desktop`, retains third-party
license notices, and copies only allowlisted tracked first-party source. It never
copies a developer virtual environment, `.env`, databases or private artifacts.
Node and managed Python come from the builder's installation; `build.json` records
the application commit and Node version. Builds are architecture-specific.

For notarization, submit the exact signed DMG using your own Keychain profile:

```sh
xcrun notarytool submit .release/TradeMaster-0.1.0-macOS-arm64.dmg --keychain-profile YOUR_PROFILE --wait
xcrun stapler staple .release/TradeMaster-0.1.0-macOS-arm64.dmg
spctl --assess --type open --context context:primary-signature --verbose .release/TradeMaster-0.1.0-macOS-arm64.dmg
shasum -a 256 .release/TradeMaster-0.1.0-macOS-arm64.dmg
```

Never put signing credentials or notarization passwords in source control.
