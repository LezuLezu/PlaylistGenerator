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
# Dynamisch alle SOURCE_PLAYLIST_* variabelen ophalen uit .env
playlist_urls = []
for key in sorted(os.environ):
    k = key.strip()
    if k.startswith("SOURCE_PLAYLIST_"):
        val = os.getenv(key) or os.getenv(k)
        if val:
            playlist_urls.append(str(val).strip().strip('"').strip("'"))

AANTAL_PLAYLISTS = 5
DUUR_PER_PLAYLIST_MIN = (60 * 10)
PLAYLIST_NAMEN = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag"]
# Override with PLAYLIST_PREFIX (e.g. VasioVibesAuto for CI so production lists stay untouched).
PLAYLIST_PREFIX = (os.getenv("PLAYLIST_PREFIX") or "VasioVibes").strip() or "VasioVibes"

# =============================
# HELPERS
# =============================
def extract_playlist_id(url):
    return url.split("playlist/")[1].split("?")[0]

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

def find_playlist_id_by_name(name):
    """Return playlist id if user has a playlist with this exact name, else None."""
    offset = 0
    limit = 50
    while True:
        result = sp.current_user_playlists(limit=limit, offset=offset)
        for pl in result.get("items") or []:
            if pl.get("name") == name:
                return pl["id"]
        if not result.get("next"):
            return None
        offset += limit


def create_or_update_playlist(name, track_ids):
    """Create a new playlist or replace tracks in an existing one with the same name."""
    existing_id = find_playlist_id_by_name(name)
    if existing_id:
        # Update existing playlist (API allows max 100 items per replace, then add rest)
        sp.playlist_replace_items(existing_id, track_ids[:100])
        for i in range(100, len(track_ids), 100):
            sp.playlist_add_items(existing_id, track_ids[i : i + 100])
        playlist = sp.playlist(existing_id)
        return playlist["external_urls"]["spotify"], "bijgewerkt"
    # Create new playlist
    try:
        playlist = sp.current_user_playlist_create(name=name, public=False)
    except spotipy.exceptions.SpotifyException as e:
        if e.http_status == 403:
            raise RuntimeError(
                "❌ 403 Forbidden bij aanmaken playlist.\n\n"
                "Je Spotify-app staat waarschijnlijk in Development Mode. Voeg je account toe:\n"
                "  1. Ga naar https://developer.spotify.com/dashboard\n"
                "  2. Open je app → Users and Access (of Settings)\n"
                "  3. Voeg het e-mailadres van je Spotify-account toe als user\n"
                "  4. Run dit script opnieuw.\n\n"
                "Zie: https://developer.spotify.com/documentation/web-api/concepts/authorization"
            ) from e
        raise
    for i in range(0, len(track_ids), 100):
        sp.playlist_add_items(
            playlist_id=playlist["id"],
            items=track_ids[i:i+100]
        )
    return playlist["external_urls"]["spotify"], "aangemaakt"

# =============================
# MAIN FLOW
# =============================
def main():
    for url in playlist_urls:
        print(f"\n🎵 Verwerken playlist: {url}")
        playlist_id = extract_playlist_id(url)

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

        print("Playlists aanmaken of bijwerken op Spotify...")
        for i, track_ids in enumerate(generated):
            day_lower = PLAYLIST_NAMEN[i].lower()
            name = f"{PLAYLIST_PREFIX}_{day_lower}"
            url, status = create_or_update_playlist(name, track_ids)
            print(f"✅ {name} ({status}): {url}")

if __name__ == "__main__":
    main()
