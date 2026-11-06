from .base import Store
from .memory import MemoryStore


def build_store(backend: str, project: str = "") -> Store:
    """memory: local dev and tests.
    firestore: Google Cloud, or Floci when FIRESTORE_EMULATOR_HOST=localhost:4588 is set
    (the Firestore client library routes to the emulator by itself)."""
    if backend == "memory":
        return MemoryStore()
    if backend == "firestore":
        from google.cloud import firestore

        from .firestore import FirestoreStore

        return FirestoreStore(firestore.Client(project=project or None))
    raise ValueError(f"unknown STORE_BACKEND {backend!r} (use 'memory' or 'firestore')")


__all__ = ["Store", "MemoryStore", "build_store"]
