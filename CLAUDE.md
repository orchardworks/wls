# finder-pane

## Language

All code, comments, commit messages, documentation, and generated text must be in English.

## Style

- Zero external dependencies — standard library only (Python + macOS system frameworks)
- Keep it simple — this is a single-file server + single-file UI
- macOS only — it's fine to use macOS-specific APIs (Finder sidebar, NSWorkspace, etc.)

## Testing

- Run tests with `.venv/bin/python -m pytest tests/ -v`
- Run tests before committing

## Releasing

1. Bump `VERSION` in `cli.py`
2. Commit and push to main
3. Tag and push: `git tag v<VERSION> && git push origin v<VERSION>`
4. GitHub Actions (`.github/workflows/release.yml`) will automatically:
   - Create a GitHub Release
   - Open a PR on `orchardworks/homebrew-tap` with updated formula (version + sha256)
5. Merge the PR on homebrew-tap
