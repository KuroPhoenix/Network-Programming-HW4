import json
import shutil
from pathlib import Path
import secrets
import tarfile
from dataclasses import dataclass, field

from server.core.game_manager import GameManager
from loguru import logger
@dataclass
class UploadSession(order=True):
    file_obj: any
    tmp_dir: Path = field(default_factory=Path)
    archive_path: Path = field(default_factory=Path)
    manifest_path: Path = field(default_factory=Path)
    received: int = 0
    seq: int = 0

@dataclass
class DownloadSession(order=True):
    download_id: str
    tmp_dir: Path = field(default_factory=Path)
    archive_path: Path = field(default_factory=Path)
    manifest_path: Path = field(default_factory=Path)
    sent: int = 0
    seq: int = 0

REQUIRED = ["game_name", "version", "type", "max_players", "description", "server", "client"]
class StorageManager:
    def __init__(self):
        logger.remove()
        logger.add("storage_manager.log", rotation="1 MB", level="INFO", mode="w")
        self.base = Path(__file__).resolve().parent.parent / "cloudGames"
        self.base.mkdir(parents=True, exist_ok=True)
        self.tmpdir = Path(__file__).resolve().parent.parent / "cloudGames" / "tmp"
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.uploadID_to_info: dict[str, UploadSession] = dict()
        self.uploadID_to_metadata: dict[str, dict] = dict()
        self.downloadID_to_info: dict[str, DownloadSession] = dict()
        self.downloadID_to_metadata: dict[str, dict] = dict()

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
        upload_id = secrets.token_hex(16)
        game_path_tmp = self.tmpdir / upload_id
        game_path_tmp.mkdir(parents=True, exist_ok=True)
        game_path = game_path_tmp / "upload.tar.gz"
        file = game_path.open("wb")
        self.uploadID_to_info[upload_id] = UploadSession(file, game_path_tmp, game_path)
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
            raise ValueError("unknown upload_id")
        if seq != sess.seq:
            raise ValueError("out-of-order chunk")
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
        manifest, stage_dir = self._verify_upload(upload_id)

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

        shutil.rmtree(sess.tmp_dir, ignore_errors=True)
        self.uploadID_to_info.pop(upload_id, None)
        self.uploadID_to_metadata.pop(upload_id, None)
        return {"path": str(final_dir), "manifest": manifest}

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

# =============================| User-Oriented |===================================================

    def init_download_verification(self, metadata: dict):
        """
        Prepare a staged tarball for download. Expects metadata to contain game_name, version, and game_folder.
        """
        if not metadata or "game_name" not in metadata:
            raise ValueError("metadata missing game_name")
        game_folder = metadata.get("game_folder") or ""
        if not game_folder:
            raise ValueError("metadata missing game_folder")
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
        return download_id

    def read_download_chunk(self, download_id: str, seq: int, chunk_size: int = 64 * 1024):
        """
        Read sequential chunks from a prepared archive.
        """
        sess = self.downloadID_to_info.get(download_id)
        if not sess:
            raise ValueError("unknown download_id")
        if seq != sess.seq:
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
        if not sess:
            raise ValueError("unknown download_id")
        shutil.rmtree(sess.tmp_dir, ignore_errors=True)
        return True

