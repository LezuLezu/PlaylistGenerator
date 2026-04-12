Playlist generator for Spotify
Configured for VasioVibes

Splits one or more source playlists into several same-length playlists (e.g. weekday lists). Each generated playlist has **no duplicate tracks**.

### Setup

1. **Create a venv and install dependencies** (if not already done):
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

2. **Configure `.env`** with your Spotify app credentials and playlist ids:
   - `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI` (e.g. `http://127.0.0.1:8888/callback`)
   - `SOURCE_PLAYLIST_1`, `SOURCE_PLAYLIST_2`, … — Spotify **playlist id** or full `open.spotify.com/playlist/…` URL
   - `TARGET_PLAYLIST_ID_1` … `TARGET_PLAYLIST_ID_5` — ids of the five existing playlists (Maandag … Vrijdag order) to overwrite each run

   If port 8888 is in use, the script will try 8889–8892. In your [Spotify app](https://developer.spotify.com/dashboard) under **Redirect URIs**, add: `http://127.0.0.1:8888/callback` through `http://127.0.0.1:8892/callback` so the fallback works.

### Run

```bash
.venv/bin/python generate.py
```

The first run (without `SPOTIFY_REFRESH_TOKEN`) prints a long Spotify URL and saves it to `spotify_auth_url.txt`. If the link opens to a white screen, copy the URL and open it in **Chrome or Edge on Windows** (not the WSL browser). Log in, then you’ll be sent to a blank/white page—copy the **redirect** URL from the address bar (e.g. `http://127.0.0.1:8889/callback?code=...`) and paste it into the terminal. After that, use the refresh token in `.env` or GitHub Actions secrets; the script only **updates** the five target playlists by id.
