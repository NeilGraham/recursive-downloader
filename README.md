# Recursive Downloader

## Example

```bash
./bin/recursive-dl \
    'https://downloads.khinsider.com/game-soundtracks/album/metal-gear-solid-4-guns-of-the-patriots-the-complete-soundtrack' \
    --search *.mp3 *.flac \
    --mode chrome
```

- From a given URL, finds all links ending with '.mp3', then recursively finds nested links ending with '.flac' and downloads from those links.
- `--mode chrome` indicates to use a Chrome webdriver (Selenium). By default is set to `--mode requests`.
- Both `requests` and Selenium modes now support concurrent processing with `--workers` for improved performance.

## Performance Modes

- **`--mode requests`**: Fast, lightweight HTTP requests with concurrent processing support
- **`--mode chrome`**: Full browser automation for JavaScript-heavy or protected sites
- **`--mode firefox`**: Alternative browser option for compatibility

Use `--workers N` to control concurrency (default: 4)
