import chromadb
from app.config import settings


class ChromaClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        return cls._instance

    @property
    def client(self) -> chromadb.ClientAPI:
        return self._client

    def get_or_create_collection(self, name: str, metadata: dict | None = None):
        return self._client.get_or_create_collection(
            name=name,
            metadata=metadata or {"hnsw:space": "cosine"},
        )

    def get_collection(self, name: str):
        return self._client.get_collection(name=name)

    def delete_collection(self, name: str):
        try:
            self._client.delete_collection(name=name)
        except Exception:
            pass


def get_novel_collection_name(novel_id: int, collection_type: str) -> str:
    return f"novel_{novel_id}_{collection_type}"


def get_kb_collection_name(kb_id: int) -> str:
    return f"kb_{kb_id}"


chroma_client = ChromaClient()
