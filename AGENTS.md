# Cross-platform development rule

RosterMate supports macOS and Windows from the same shared Python and browser-GUI codebase.

For every functional change or improvement:

1. Keep shared application behavior platform-neutral unless an operating-system distinction is required.
2. Update both macOS and Windows launch, install, autostart, path, and documentation flows whenever the change affects them.
3. Add or update automated tests for shared behavior and for each affected platform adapter.
4. Keep `docs/INSTALL_MACOS.md` and `docs/INSTALL_WINDOWS.md` aligned.
5. Use the same GUI and screenshots for both platforms unless a genuinely native platform UI is introduced.
6. Never commit personal credentials, tokens, domains, driver numbers, IP addresses, or local deployment configuration.
7. Do not claim a platform-specific behavior was tested on physical hardware unless it actually was; distinguish automated adapter tests from real-device verification.
8. Keep `.github/workflows/platform-tests.yml` passing on both `macos-latest` and `windows-latest`.

Platform entry points:

- macOS installation: `install.command`
- macOS start: `run.command` and `RosterMate.app`
- Windows installation: `install-windows.cmd` / `install-windows.ps1`
- Windows start: `run-windows.cmd` / `run-windows.ps1`
- Autostart adapters: `launch_agent.py`
- Shared application: `app.py` and the remaining Python modules
