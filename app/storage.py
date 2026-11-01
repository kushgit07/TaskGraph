"""Storage adapter interface. Shipped implementation is local filesystem;
the interface is deliberately shaped so an S3Adapter could be dropped in
without touching callers — not built/deployed here (see README), but the
seam exists on purpose.
"""
import os
import shutil
from abc import ABC, abstractmethod

from app.config import settings


class StorageAdapter(ABC):
    @abstractmethod
    def save(self, run_id: str, key: str, source_path: str) -> str:
        """Persist the file at source_path under (run_id, key). Returns a
        storage path/URI that resolve() can later use to fetch it."""

    @abstractmethod
    def resolve(self, storage_path: str) -> str:
        """Return a local filesystem path to the artifact's bytes,
        materializing it if necessary."""


class LocalStorageAdapter(StorageAdapter):
    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or settings.storage_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def save(self, run_id: str, key: str, source_path: str) -> str:
        run_dir = os.path.join(self.base_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        dest = os.path.join(run_dir, key)
        shutil.copyfile(source_path, dest)
        return dest

    def resolve(self, storage_path: str) -> str:
        return storage_path


default_storage = LocalStorageAdapter()
