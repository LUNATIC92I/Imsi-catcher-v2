"""Protection des fichiers importés.

* contrôle de l'extension et de la taille ;
* copie dans une zone de conservation interne avec un nom dérivé du SHA-256
  (aucun nom fourni par l'utilisateur n'est réutilisé tel quel → pas de
  traversée de répertoire) ;
* fichier conservé en lecture seule, empreinte enregistrée pour contrôle
  d'intégrité ultérieur.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

ALLOWED_EXTENSIONS = {".csv", ".json", ".npz"}
DEFAULT_MAX_BYTES = 200 * 1024 * 1024


class ImportRejected(ValueError):
    pass


@dataclass(frozen=True)
class ProtectedFile:
    original_name: str
    stored_path: Path
    sha256: str
    size_bytes: int


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def protect_import(path: str | Path, vault_dir: str | Path,
                   max_bytes: int = DEFAULT_MAX_BYTES) -> ProtectedFile:
    src = Path(path)
    if not src.is_file():
        raise ImportRejected(f"fichier introuvable : {src}")
    if src.is_symlink():
        raise ImportRejected("les liens symboliques ne sont pas acceptés")
    ext = src.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ImportRejected(f"extension non autorisée : {ext or '(aucune)'}")
    size = src.stat().st_size
    if size == 0:
        raise ImportRejected("fichier vide")
    if size > max_bytes:
        raise ImportRejected(f"fichier trop volumineux ({size} octets > {max_bytes})")

    digest = sha256_file(src)
    vault = Path(vault_dir)
    vault.mkdir(parents=True, exist_ok=True)
    dest = vault / f"{digest}{ext}"
    if not dest.exists():
        shutil.copyfile(src, dest)
        os.chmod(dest, stat.S_IRUSR | stat.S_IRGRP)
    return ProtectedFile(original_name=src.name, stored_path=dest, sha256=digest, size_bytes=size)


def verify_integrity(protected: ProtectedFile) -> bool:
    return protected.stored_path.is_file() and sha256_file(protected.stored_path) == protected.sha256


def secure_delete_file(path: str | Path, passes: int = 1) -> None:
    """Écrase le contenu avant suppression (best effort : sans garantie sur
    SSD/systèmes journalisés, voir documentation)."""
    p = Path(path)
    if not p.exists():
        return
    os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    size = p.stat().st_size
    with open(p, "r+b") as fh:
        for _ in range(max(1, passes)):
            fh.seek(0)
            fh.write(os.urandom(size))
            fh.flush()
            os.fsync(fh.fileno())
    p.unlink()
