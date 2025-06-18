# Recursive Downloader

## Example

```bash
python run.py \
    'https://downloads.khinsider.com/game-soundtracks/album/metal-gear-solid-4-guns-of-the-patriots-the-complete-soundtrack' \
    --search *.mp3 *.flac \
    --mode chrome
```

- From a given URL, finds all links ending with '.mp3', then recursively finds nested links ending with '.flac' and downloads from those links.
- `--mode chrome` indicates to use a Chrome webdriver (Selenium). By default is set to `--mode requests`.
