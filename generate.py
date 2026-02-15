import os
import random
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# =============================
# SETUP
# =============================
load_dotenv()

scope = "playlist-modify-public playlist-read-private"

sp = spotipy.Spotify(
    auth_manager=SpotifyOAuth(scope=scope)
)

user_id = sp.current_user()["id"]

# =============================
# CONFIG
# =============================
# Dynamisch alle SOURCE_PLAYLIST_* variabelen ophalen uit .env
playlist_urls = [
    os.getenv(key) for key in os.environ if key.startswith("SOURCE_PLAYLIST_")
]

AANTAL_PLAYLISTS = 5
DUUR_PER_PLAYLIST_MIN = (60 * 8)
PLAYLIST_NAMEN = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag"]

# =============================
# HELPERS
# =============================
def extract_playlist_id(url):
    return url.split("playlist/")[1].split("?")[0]

def get_all_tracks(playlist_id):
    tracks = []
    try:
        results = sp.playlist_items(
            playlist_id,
            additional_types=["track"],
            market=None
        )

        while results:
            for item in results["items"]:
                track = item["track"]
                if track:
                    tracks.append({
                        "id": track["id"],
                        "duration_ms": track["duration_ms"],
                        "name": track["name"]
                    })
            results = sp.next(results) if results["next"] else None

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
    playlists = []
    target_duration = duur_minuten * 60 * 1000
    available_tracks = tracks.copy()
    random.shuffle(available_tracks)

    for i in range(aantal):
        current_duration = 0
        playlist_tracks = []
        while available_tracks and current_duration < target_duration:
            track = available_tracks.pop()
            playlist_tracks.append(track["id"])
            current_duration += track["duration_ms"]
        playlists.append(playlist_tracks)
    return playlists

def create_playlist(name, track_ids):
    playlist = sp.user_playlist_create(
        user=user_id,
        name=name,
        public=True
    )
    for i in range(0, len(track_ids), 100):
        sp.playlist_add_items(
            playlist_id=playlist["id"],
            items=track_ids[i:i+100]
        )
    return playlist["external_urls"]["spotify"]

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

        print("Playlists aanmaken op Spotify...")
        for i, track_ids in enumerate(generated):
            name = f"{PLAYLIST_NAMEN[i]} - {playlist_id[:5]}"  # voeg korte id toe zodat naam uniek is
            url = create_playlist(name, track_ids)
            print(f"✅ {name}: {url}")

if __name__ == "__main__":
    main()
