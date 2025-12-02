import json
from pathlib import Path
from typing import List, Dict, Any

class LocalGameManager:
    """
    Utility to scan local downloaded games and read their manifests.
    Looks for manifest.json under user/downloads/<game_name>/.
    """

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent / "downloads"

    def _list_games(self) -> List[Path]:
        """
        Return a list of game directories under base_dir that contain manifest.json.
        """
        if not self.base_dir.exists():
            return []
        return [p for p in self.base_dir.iterdir() if p.is_dir() and (p / "manifest.json").exists()]

    def load_manifest(self, game_dir: Path) -> Dict[str, Any]:
        """
        Read manifest.json from the given game directory.
        """
        manifest_path = game_dir / "manifest.json"
        with manifest_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def list_manifests(self) -> List[Dict[str, Any]]:
        """
        Return a list of minimal manifest info for all local games.
        Only includes fields aligned with games.db: author (unknown locally), game_name, version, type.
        """
        manifests = []
        for game_dir in self._list_games():
            try:
                manifest = self.load_manifest(game_dir)
                entry = {
                    "game_name": manifest.get("game_name"),
                    "version": manifest.get("version"),
                    "type": manifest.get("type"),
                    "description": manifest.get("description"),
                    "uploaded": manifest.get("uploaded"),
                    "_path": str(game_dir),
                }
                manifests.append(entry)
            except Exception:
                continue
        return manifests