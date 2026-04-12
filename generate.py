import os
import random
import socket
import time
from dotenv import load_dotenv
import spotipy
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyOAuth

# =============================
# SETUP
# =============================
load_dotenv()

scope = "playlist-modify-public playlist-modify-private playlist-read-private user-read-private"


def _pick_redirect_port():
    base = "http://127.0.0.1"
    for port in range(8888, 8893):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return f"{base}:{port}/callback"
        except OSError:
            continue
    return os.getenv("SPOTIPY_REDIRECT_URI", f"{base}:8888/callback")


def _spotify_from_refresh_token():
    refresh = os.getenv("SPOTIFY_REFRESH_TOKEN", "").strip()
    if not refresh:
        return None
    client_id = (os.getenv("SPOTIPY_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("SPOTIPY_CLIENT_SECRET") or "").strip()
    redirect_uri = (os.getenv("SPOTIPY_REDIRECT_URI") or "http://127.0.0.1:8888/callback").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "SPOTIFY_REFRESH_TOKEN is set but SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET are missing."
        )
    # MemoryCacheHandler must include scope and expires_at or spotipy's
    # validate_token() drops the entry and falls back to interactive OAuth.
    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope,
        open_browser=False,
        cache_handler=MemoryCacheHandler(
            {
                "refresh_token": refresh,
                "scope": scope,
                "expires_at": int(time.time()) - 3600,
            }
        ),
    )
    return spotipy.Spotify(auth_manager=auth_manager)


if not os.getenv("SPOTIFY_REFRESH_TOKEN", "").strip():
    _redirect_uri = _pick_redirect_port()
    if _redirect_uri != os.getenv("SPOTIPY_REDIRECT_URI", "").strip():
        os.environ["SPOTIPY_REDIRECT_URI"] = _redirect_uri


class _SpotifyOAuthWithPrompt(SpotifyOAuth):
    """Re-prompt with clear instructions if user pastes the login URL instead of the redirect URL."""

    def _get_auth_response_interactive(self, open_browser=False):
        if open_browser:
            self._open_auth_url()
            prompt = "Enter the URL you were redirected to: "
        else:
            url = self.get_authorize_url()
            auth_file = os.path.join(os.path.dirname(__file__) or ".", "spotify_auth_url.txt")
            try:
                with open(auth_file, "w") as f:
                    f.write(url)
                print(f"STEP 1 — Auth URL saved to: {auth_file}")
                print("        If the link opens in a browser and you get a WHITE screen:")
                print("        • Open that file from Windows (e.g. \\\\wsl$\\...\\PlaylistGenerator\\spotify_auth_url.txt)")
                print("        • Copy the URL and paste it into Chrome or Edge on Windows (not the WSL browser).")
                print()
            except OSError:
                pass
            print("Or copy this URL and open it in Chrome/Edge on Windows:")
            print()
            print(url)
            print()
            print("STEP 2 — Log in on Spotify in that browser.")
            print("STEP 3 — You'll be redirected to a blank page. Copy the NEW URL from the address bar and paste it below.")
            print()
            prompt = "Paste the redirect URL here: "
        while True:
            response = self._get_user_input(prompt).strip()
            if "code=" in response and ("/callback" in response or "callback?" in response):
                break
            if response and not response.startswith("http://127.0.0.1") and "accounts.spotify.com/authorize" in response:
                print("\nThat's the login URL. After you log in, Spotify sends you to a different URL.")
                print("Copy the address bar URL from the *redirect* page (it starts with http://127.0.0.1:.../callback?code=...).\n")
            else:
                print("\nPaste the full URL from your browser's address bar after logging in (it should contain ?code=).\n")
            prompt = "Paste the REDIRECT URL: "
        state, code = SpotifyOAuth.parse_auth_response_url(response)
        if self.state is not None and self.state != state:
            raise spotipy.exceptions.SpotifyStateError(self.state, state)
        return code


# CI / automation: SPOTIFY_REFRESH_TOKEN + app credentials (no browser).
# Local: interactive OAuth (open_browser=False for WSL/headless).
sp = _spotify_from_refresh_token()
if sp is None:
    if os.getenv("GITHUB_ACTIONS") == "true":
        missing = [
            name
            for name, val in (
                ("SPOTIFY_REFRESH_TOKEN", os.getenv("SPOTIFY_REFRESH_TOKEN", "")),
                ("SPOTIPY_CLIENT_ID", os.getenv("SPOTIPY_CLIENT_ID", "")),
                ("SPOTIPY_CLIENT_SECRET", os.getenv("SPOTIPY_CLIENT_SECRET", "")),
                ("SPOTIPY_REDIRECT_URI", os.getenv("SPOTIPY_REDIRECT_URI", "")),
            )
            if not (val or "").strip()
        ]
        raise RuntimeError(
            "GitHub Actions cannot use interactive Spotify login (no stdin, no browser). "
            "Use refresh-token auth: set repository secrets and pass them in the workflow job env. "
            + (
                f"Missing or empty in this run: {', '.join(missing)}. "
                if missing
                else "Secrets may be unset or not exposed to this workflow (e.g. wrong environment, or fork PR). "
            )
            + "If the authorize URL shows client_id=, SPOTIPY_CLIENT_ID never reached the runner."
        )
    sp = spotipy.Spotify(
        auth_manager=_SpotifyOAuthWithPrompt(scope=scope, open_browser=False)
    )

_current_user = sp.current_user()
user_id = _current_user["id"]
user_country = _current_user.get("country") or "US"

# =============================
# CONFIG
# =============================
AANTAL_PLAYLISTS = 5
DUUR_PER_PLAYLIST_MIN = (60 * 10)
PLAYLIST_NAMEN = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag"]


def normalize_playlist_id(value):
    """Accept bare Spotify playlist id, open.spotify.com URL, or spotify:playlist: URI."""
    s = str(value).strip().strip('"').strip("'")
    if not s:
        return ""
    low = s.lower()
    idx = low.find("playlist/")
    if idx != -1:
        part = s[idx + len("playlist/") :]
        return part.split("?", 1)[0].split("#", 1)[0].strip()
    if low.startswith("spotify:playlist:"):
        return s.split(":", 2)[2].split("?", 1)[0].strip()
    return s


source_playlist_ids = []
for key in sorted(os.environ):
    k = key.strip()
    if k.startswith("SOURCE_PLAYLIST_"):
        val = os.getenv(key) or os.getenv(k)
        if val:
            pid = normalize_playlist_id(val)
            if pid:
                source_playlist_ids.append(pid)

target_playlist_ids = []
for i in range(1, AANTAL_PLAYLISTS + 1):
    val = os.getenv(f"TARGET_PLAYLIST_ID_{i}", "")
    pid = normalize_playlist_id(val) if val else ""
    target_playlist_ids.append(pid)

# =============================
# HELPERS
# =============================

def get_all_tracks(playlist_id):
    tracks = []
    try:
        # Use user's market so track details aren't null (regional availability)
        for market in ("from_token", user_country):
            results = sp.playlist_items(
                playlist_id,
                additional_types=["track"],
                market=market
            )
            tracks = []
            while results:
                for item in results.get("items") or []:
                    # API can return track under "track" or "item" (newer format)
                    track = item.get("track") or item.get("item")
                    if track and track.get("id") and track.get("duration_ms") is not None:
                        # Skip episodes (podcasts), only include music tracks
                        if track.get("type") == "episode":
                            continue
                        tracks.append({
                            "id": track["id"],
                            "duration_ms": track["duration_ms"],
                            "name": track["name"]
                        })
                results = sp.next(results) if results["next"] else None
            if tracks:
                break

    except spotipy.exceptions.SpotifyException as e:
        raise RuntimeError(
            f"❌ Kan playlist niet uitlezen (403 Forbidden).\n"
            f"Mogelijke oorzaken:\n"
            f"- Playlist is Spotify curated/editorial\n"
            f"- Tracks niet beschikbaar in jouw regio\n"
            f"- Playlist leeg of recent aangemaakt\n"
            f"Playlist ID: {playlist_id}\n"
            f"Error: {str(e)}"
        )

    return tracks

def remove_duplicates(tracks):
    unique = {}
    for track in tracks:
        unique[track["id"]] = track
    return list(unique.values())

def generate_playlists(tracks, aantal, duur_minuten):
    """Build `aantal` playlists from `tracks`, each ~`duur_minuten` long. No duplicate tracks per playlist."""
    playlists = []
    target_duration = duur_minuten * 60 * 1000  # ms
    available_tracks = tracks.copy()
    random.shuffle(available_tracks)

    for i in range(aantal):
        current_duration = 0
        playlist_tracks = []
        seen_ids = set()  # no duplicate track IDs per playlist
        while available_tracks and current_duration < target_duration:
            track = available_tracks.pop()
            if track["id"] in seen_ids:
                continue
            seen_ids.add(track["id"])
            playlist_tracks.append(track["id"])
            current_duration += track["duration_ms"]
        playlists.append(playlist_tracks)
    return playlists


def _playlist_web_url(playlist_id):
    return f"https://open.spotify.com/playlist/{playlist_id}"


def replace_playlist_tracks(playlist_id, track_ids):
    """Replace contents of an existing playlist (max 100 per replace/add call)."""
    sp.playlist_replace_items(playlist_id, track_ids[:100])
    for i in range(100, len(track_ids), 100):
        sp.playlist_add_items(playlist_id, track_ids[i : i + 100])
    return _playlist_web_url(playlist_id), "bijgewerkt"


# =============================
# MAIN FLOW
# =============================
def main():
    missing_targets = [
        f"TARGET_PLAYLIST_ID_{i + 1}"
        for i, pid in enumerate(target_playlist_ids)
        if not pid
    ]
    if missing_targets:
        raise RuntimeError(
            "Set all target playlist ids (empty env): " + ", ".join(missing_targets)
        )
    if not source_playlist_ids:
        raise RuntimeError(
            "No source playlists: set SOURCE_PLAYLIST_1, SOURCE_PLAYLIST_2, … "
            "(Spotify playlist id or full playlist URL)."
        )

    for playlist_id in source_playlist_ids:
        print(f"\n🎵 Verwerken bron-playlist: {playlist_id}")

        print("Tracks ophalen...")
        tracks = get_all_tracks(playlist_id)
        print(f"Totaal tracks opgehaald: {len(tracks)}")

        tracks = remove_duplicates(tracks)
        print(f"Unieke tracks: {len(tracks)}")

        totale_duur = sum(t["duration_ms"] for t in tracks)
        benodigde_duur = AANTAL_PLAYLISTS * DUUR_PER_PLAYLIST_MIN * 60 * 1000
        if totale_duur < benodigde_duur:
            print("❌ Niet genoeg muziek in bronplaylist voor gewenste output.")
            continue

        print("Playlists genereren...")
        generated = generate_playlists(tracks, AANTAL_PLAYLISTS, DUUR_PER_PLAYLIST_MIN)

        print("Playlists bijwerken op Spotify…")
        for i, track_ids in enumerate(generated):
            day = PLAYLIST_NAMEN[i]
            tid = target_playlist_ids[i]
            url, status = replace_playlist_tracks(tid, track_ids)
            print(f"✅ {day} → {tid} ({status}): {url}")

if __name__ == "__main__":
    main()
