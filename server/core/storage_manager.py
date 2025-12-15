import json
import shutil
from pathlib import Path
import secrets
import tarfile
from dataclasses import dataclass, field

from server.core.game_manager import GameManager
from loguru import logger
from shared.logger import ensure_global_logger, log_dir

# Module-specific logging
LOG_DIR = log_dir()
ensure_global_logger()
logger.add(LOG_DIR / "storage_manager.log", rotation="1 MB", level="INFO", filter=lambda r: r["file"] == "storage_manager.py")
logger.add(LOG_DIR / "storage_manager_errors.log", rotation="1 MB", level="ERROR", filter=lambda r: r["file"] == "storage_manager.py")
@dataclass(order=True)
class UploadSession:
    file_obj: any
    tmp_dir: Path = field(default_factory=Path)
    archive_path: Path = field(default_factory=Path)
    manifest_path: Path = field(default_factory=Path)
    received: int = 0
    seq: int = 0
    expected_size: int | None = None
    expected_checksum: str | None = None
    chunk_size: int = 64 * 1024

@dataclass(order=True)
class DownloadSession:
    download_id: str
    tmp_dir: Path = field(default_factory=Path)
    archive_path: Path = field(default_factory=Path)
    manifest_path: Path = field(default_factory=Path)
    sent: int = 0
    seq: int = 0

REQUIRED = ["game_name", "version", "type", "max_players", "description", "server", "client"]
class StorageManager:
    def __init__(self):
        self.base = Path(__file__).resolve().parent.parent / "cloudGames"
        self.base.mkdir(parents=True, exist_ok=True)
        self.tmpdir = Path(__file__).resolve().parent.parent / "cloudGames" / "tmp"
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.uploadID_to_info: dict[str, UploadSession] = dict()
        self.uploadID_to_metadata: dict[str, dict] = dict()
        self.downloadID_to_info: dict[str, DownloadSession] = dict()
        self.downloadID_to_metadata: dict[str, dict] = dict()
        self.download_meta_cache: dict[str, dict] = dict()

# ============================| Dev-Oriented |=============================================

    def init_upload_verification(self, expected_metadata: dict):
        """
        The First step of game uploading
         returns upload_id and internally allocates a temp file path.
        :param expected_metadata: request/DB data to validate manifest against
        :return:
        """
        if not expected_metadata or "game_name" not in expected_metadata:
            raise ValueError("expected_metadata missing game_name")
        expected_size = expected_metadata.get("size_bytes")
        expected_checksum = expected_metadata.get("checksum")
        upload_id = secrets.token_hex(16)
        game_path_tmp = self.tmpdir / upload_id
        game_path_tmp.mkdir(parents=True, exist_ok=True)
        game_path = game_path_tmp / "upload.tar.gz"
        file = game_path.open("wb")
        self.uploadID_to_info[upload_id] = UploadSession(
            file, game_path_tmp, game_path, expected_size=expected_size if expected_size else None, expected_checksum=expected_checksum if expected_checksum else None
        )
        self.uploadID_to_metadata[upload_id] = expected_metadata
        return upload_id

    def append_chunk(self, upload_id, chunk: bytes, seq: int):
        """
        Second step of game uploading: Accept sequential chunk stream and writing into file.
        :param upload_id:
        :param chunk:
        :param seq:
        :return:
        """
        sess = self.uploadID_to_info.get(upload_id)
        if not sess:
            logger.error(f"append_chunk unknown upload_id={upload_id}")
            raise ValueError("unknown upload_id")
        if seq != sess.seq:
            logger.warning(f"append_chunk out-of-order upload_id={upload_id} expected={sess.seq} got={seq}")
            raise ValueError("out-of-order chunk")
        if sess.expected_size is not None and sess.received + len(chunk) > sess.expected_size:
            raise ValueError("size overflow")
        sess.file_obj.write(chunk)
        sess.received += len(chunk)
        if seq is not None:
            sess.seq += 1

    def finalise_upload(self, upload_id: str):
        """
        Third step of game uploading.\n
        Close, stage, validate, and move the upload into its final location.\n
        Returns a dictionary containing game archive folder path and manifest file path.
        """
        sess = self.uploadID_to_info.get(upload_id)
        if not sess:
            raise ValueError("unknown upload_id")
        sess.file_obj.close()
        try:
            manifest, stage_dir = self._verify_upload(upload_id)
            if sess.expected_size is not None and sess.received != sess.expected_size:
                raise ValueError("size mismatch")
            archive_checksum = None
            if sess.expected_checksum:
                archive_checksum = self._sha256_file(sess.archive_path)
                if archive_checksum != sess.expected_checksum:
                    raise ValueError("checksum mismatch")

            game_name = manifest["game_name"]
            version = str(manifest["version"])
            if Path(game_name).is_absolute() or ".." in Path(game_name).parts:
                raise ValueError("game_name unsafe")
            if Path(version).is_absolute() or ".." in Path(version).parts:
                raise ValueError("version unsafe")

            final_dir = self.base / game_name / version
            if final_dir.exists():
                raise ValueError("target version already exists")
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            stage_dir.rename(final_dir)

            return {"path": str(final_dir), "manifest": manifest, "checksum": archive_checksum}
        except Exception as e:
            shutil.rmtree(sess.tmp_dir, ignore_errors=True)
            self.uploadID_to_info.pop(upload_id, None)
            self.uploadID_to_metadata.pop(upload_id, None)
            logger.warning(f"finalise_upload failed for {upload_id}: {e}")
            raise
        finally:
            # Clean up on success too
            shutil.rmtree(sess.tmp_dir, ignore_errors=True)
            self.uploadID_to_info.pop(upload_id, None)
            self.uploadID_to_metadata.pop(upload_id, None)

    def _verify_upload(self, upload_id: str):
        sess = self.uploadID_to_info.get(upload_id)
        if not sess:
            raise ValueError("unknown upload_id")
        expected = self.uploadID_to_metadata.get(upload_id) or {}
        if not expected:
            raise ValueError("missing expected metadata")
        try:
            stage_dir = self._stage_verification(upload_id)
            sess.manifest_path = self._find_manifest(stage_dir)
            manifest = self._align_manifest(upload_id, expected)
            return manifest, stage_dir
        except ValueError as e:
            logger.info(f"Upload {upload_id} failed validation: {e}")
            raise e

    def _find_manifest(self, base):
        """
        Returns the path to the manifest.json file
        :param base:
        :return:
        """
        file = list(base.rglob("manifest.json"))
        if len(file) == 1:
          return file[0]
        raise ValueError("manifest.json not found or ambiguous")

    def _stage_verification(self, upload_id: str):
        sess = self.uploadID_to_info.get(upload_id)
        if sess is None:
            raise ValueError(f"Cannot find UploadSession for Upload ID {upload_id}")
        stage_dir = sess.tmp_dir / "staged"
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        stage_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(sess.archive_path, "r:gz") as tar:
            for m in tar.getmembers():
                p = stage_dir / m.name
                if not p.resolve().is_relative_to(stage_dir.resolve()):
                    raise ValueError("unsafe path in archive")
            tar.extractall(stage_dir)
        return stage_dir

    def _align_manifest(self, upload_id: str, metadata: dict):
        sess = self.uploadID_to_info.get(upload_id)
        if not sess or not sess.manifest_path:
            raise ValueError("manifest not staged")
        manifest = json.loads(Path(sess.manifest_path).read_text(encoding="utf-8"))
        for key in REQUIRED:
            if key not in manifest:
                raise ValueError(f"manifest missing {key}")
        for key in ["game_name", "type", "version"]:
            expected_val = metadata.get(key)
            if expected_val in (None, "") and key == "version":
                continue
            if manifest[key] != expected_val:
                raise ValueError(f"{key} mismatch")

        allowed_types = {"CLI", "GUI", "2P", "Multi"}
        if manifest["type"] not in allowed_types:
            raise ValueError("type invalid")
        if not isinstance(manifest["max_players"], int) or manifest["max_players"] <= 0:
            raise ValueError("max_players invalid")

        for side in ["server", "client"]:
            cfg = manifest[side]
            if not isinstance(cfg.get("command"), str) or not cfg["command"]:
                raise ValueError(f"{side}.command invalid")
            wd = cfg.get("working_dir", "")
            if Path(wd).is_absolute() or ".." in Path(wd).parts:
                raise ValueError(f"{side}.working_dir unsafe")

        for asset in manifest.get("assets", []):
            if not isinstance(asset, str):
                raise ValueError("asset path must be string")
            if Path(asset).is_absolute() or ".." in Path(asset).parts:
                raise ValueError("asset path unsafe")

        health = manifest.get("healthcheck")
        if health is not None:
            if not isinstance(health, dict):
                raise ValueError("healthcheck invalid")
            if "timeout_sec" in health and (not isinstance(health["timeout_sec"], int) or health["timeout_sec"] <= 0):
                raise ValueError("healthcheck.timeout_sec invalid")

        return manifest

    def delete_game(self, game_name: str, game_paths: list[str] | None = None) -> list[str]:
        """
        Remove stored assets for a game. Accepts explicit version paths from the DB and
        prunes the game root if it ends up empty.
        """
        if not game_name:
            raise ValueError("game_name required")
        if Path(game_name).is_absolute() or ".." in Path(game_name).parts:
            raise ValueError("game_name unsafe")
        removed: list[str] = []
        base_resolved = self.base.resolve()
        for path_str in set(game_paths or []):
            if not path_str:
                continue
            p = Path(path_str)
            try:
                resolved = p.resolve()
            except FileNotFoundError:
                resolved = p
            if not resolved.is_relative_to(base_resolved):
                logger.warning(f"skip deletion outside storage root: {p}")
                continue
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
                removed.append(str(p))
        game_root = self.base / game_name
        try:
            if game_root.exists() and not any(game_root.iterdir()):
                shutil.rmtree(game_root, ignore_errors=True)
        except FileNotFoundError:
            pass
        return removed

#=============================| User-Oriented |===================================================

    def init_download_verification(self, metadata: dict):
        """
        Prepare a staged tarball for download. Expects metadata to contain game_name, version, and game_folder.
        """
        if not metadata or "game_name" not in metadata:
            raise ValueError("metadata missing game_name")
        game_folder = self._resolve_game_folder(metadata)
        download_id = secrets.token_hex(16)
        game_path = Path(game_folder)
        if not game_path.exists():
            raise ValueError(f"Game folder not found: {game_folder}")
        manifest_path = self._find_manifest(game_path)

        tmp_dir = self.tmpdir / download_id
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        archive_path = tmp_dir / "download.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(game_path, arcname=".")

        self.downloadID_to_info[download_id] = DownloadSession(download_id, tmp_dir, archive_path, manifest_path)
        version_val = metadata.get("version")
        if version_val is None:
            version_val = ""
        self.downloadID_to_metadata[download_id] = {
            "game_name": metadata["game_name"],
            "version": str(version_val),
        }
        size_bytes = archive_path.stat().st_size
        checksum = self._sha256_file(archive_path)
        self.download_meta_cache[download_id] = {"size_bytes": size_bytes, "checksum": checksum}
        return download_id

    def read_download_chunk(self, download_id: str, seq: int, chunk_size: int = 64 * 1024):
        """
        Read sequential chunks from a prepared archive.
        """
        sess = self.downloadID_to_info.get(download_id)
        if not sess:
            logger.error(f"read_download_chunk unknown download_id={download_id}")
            raise ValueError("unknown download_id")
        if seq != sess.seq:
            logger.warning(f"read_download_chunk out-of-order download_id={download_id} expected={sess.seq} got={seq}")
            raise ValueError("out-of-order chunk")

        with sess.archive_path.open("rb") as f:
            f.seek(sess.sent)
            chunk = f.read(chunk_size)
        if chunk is None:
            chunk = b""
        sess.sent += len(chunk)
        sess.seq += 1
        total = sess.archive_path.stat().st_size
        done = sess.sent >= total
        return chunk, done

    def complete_download(self, download_id: str):
        sess = self.downloadID_to_info.pop(download_id, None)
        self.downloadID_to_metadata.pop(download_id, None)
        self.download_meta_cache.pop(download_id, None)
        if not sess:
            raise ValueError("unknown download_id")
        shutil.rmtree(sess.tmp_dir, ignore_errors=True)
        return True

    def describe_package(self, game_name: str, version: str, game_folder: str | None = None) -> dict:
        """
        Return size and checksum for a stored game package by creating a temp archive snapshot.
        """
        base_folder = self._resolve_game_folder(
            {
                "game_name": game_name,
                "version": version,
                "game_folder": game_folder,
            }
        )
        meta = {"game_name": game_name, "version": version, "game_folder": base_folder}
        download_id = self.init_download_verification(meta)
        info = self.download_meta_cache.get(download_id, {})
        # cleanup temp artifacts
        self.complete_download(download_id)
        return {"size_bytes": info.get("size_bytes", 0), "checksum": info.get("checksum")}

    def _sha256_file(self, path: Path) -> str:
        import hashlib

        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _resolve_game_folder(self, metadata: dict) -> str:
        """
        Pick a safe, existing folder for a game. Prefer the supplied game_folder if it exists;
        otherwise fall back to the storage root path derived from game_name/version.
        """
        raw_folder = metadata.get("game_folder") or ""
        game_name = metadata.get("game_name") or ""
        version = metadata.get("version")
        version_str = str(version) if version not in (None, "") else ""

        # If provided path exists, use it.
        if raw_folder:
            p = Path(raw_folder)
            if p.exists():
                return str(p)

        # Fallback to our canonical storage location.
        base_candidate = self.base / game_name
        if version_str:
            base_candidate = base_candidate / version_str
        if base_candidate.exists():
            return str(base_candidate)

        # If all else fails, keep the original (will raise later).
        return raw_folder or str(base_candidate)

