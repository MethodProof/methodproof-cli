"""OS-level Now Playing detection — polls Spotify / Music.app / MPRIS."""

import platform
import subprocess
import threading
import time

from methodproof.agents import base

_POLL_INTERVAL = 10
_HEARTBEAT_INTERVAL = 60


def _get_now_playing_macos() -> dict[str, str] | None:
    script = (
        'set output to ""\n'
        'if application "Spotify" is running then\n'
        '  tell application "Spotify"\n'
        '    if player state is playing then\n'
        '      set output to name of current track & "|||" & artist of current track & "|||spotify_desktop"\n'
        '    end if\n'
        '  end tell\n'
        'end if\n'
        'if output is "" and application "Music" is running then\n'
        '  tell application "Music"\n'
        '    if player state is playing then\n'
        '      set output to name of current track & "|||" & artist of current track & "|||apple_music_desktop"\n'
        '    end if\n'
        '  end tell\n'
        'end if\n'
        'return output'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        parts = result.stdout.strip().split("|||")
        if len(parts) != 3 or not parts[0]:
            return None
        return {"track": parts[0], "artist": parts[1], "player": parts[2]}
    except Exception:
        return None


def _get_now_playing_linux() -> dict[str, str] | None:
    try:
        result = subprocess.run(
            ["playerctl", "metadata", "--format", "{{artist}}|||{{title}}|||{{playerName}}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().split("|||")
        if len(parts) != 3 or not parts[1]:
            return None
        player_map = {"spotify": "spotify_desktop", "chromium": "unknown", "firefox": "unknown"}
        return {"track": parts[1], "artist": parts[0], "player": player_map.get(parts[2].lower(), "unknown")}
    except FileNotFoundError:
        return None
    except Exception:
        return None


def start(stop: threading.Event) -> None:
    getter = (
        _get_now_playing_macos if platform.system() == "Darwin"
        else _get_now_playing_linux if platform.system() == "Linux"
        else None
    )
    if getter is None:
        base.log("info", "music.unsupported_platform", platform=platform.system())
        return

    base.log("info", "music.started")
    last_track_key = ""
    last_emit_time = 0.0

    while not stop.is_set():
        info = getter()
        now = time.time()

        if info:
            track_key = f"{info['artist']}::{info['track']}"
            if track_key != last_track_key:
                base.emit("music_playing", {
                    "track": info["track"], "artist": info["artist"],
                    "source": "os_media", "player": info["player"],
                    "event_kind": "track_change",
                })
                last_track_key = track_key
                last_emit_time = now
            elif now - last_emit_time >= _HEARTBEAT_INTERVAL:
                base.emit("music_playing", {
                    "track": info["track"], "artist": info["artist"],
                    "source": "os_media", "player": info["player"],
                    "event_kind": "heartbeat",
                })
                last_emit_time = now
        elif last_track_key:
            last_track_key = ""

        stop.wait(_POLL_INTERVAL)

    base.log("info", "music.stopped")
