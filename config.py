"""
Second Brain — Configuration

Single source of configuration for all scripts.
Reads from .env file, falls back to environment variables, then defaults.

Usage:
    from config import cfg
    print(cfg.ARCADEDB_URL)
    print(cfg.ARCADEDB_AUTH)  # base64 encoded
"""
import os
import base64
from pathlib import Path


def _load_env_file():
    """Load .env file from project root or home directory."""
    candidates = [
        Path(__file__).parent / ".env",
        Path.home() / ".env",
    ]
    for path in candidates:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    val = val.strip().strip("\"'")
                    os.environ.setdefault(key.strip(), val)
            return str(path)
    return None


class Config:
    def __init__(self):
        self._env_file = _load_env_file()

        # --- ArcadeDB ---
        self.ARCADEDB_HOST = os.getenv("ARCADEDB_HOST", "localhost")
        self.ARCADEDB_PORT = int(os.getenv("ARCADEDB_PORT", "2480"))
        self.ARCADEDB_USER = os.getenv("ARCADEDB_USER", "root")
        self.ARCADEDB_PASSWORD = os.getenv("ARCADEDB_PASSWORD", "")
        self.ARCADEDB_DATABASE = os.getenv("ARCADEDB_DATABASE", "secondbrain")

        if not self.ARCADEDB_PASSWORD:
            raise ValueError(
                "ARCADEDB_PASSWORD is required. Set it in .env or as an environment variable."
            )

        self.ARCADEDB_URL = (
            f"http://{self.ARCADEDB_HOST}:{self.ARCADEDB_PORT}/api/v1/mcp"
        )
        self.ARCADEDB_AUTH = base64.b64encode(
            f"{self.ARCADEDB_USER}:{self.ARCADEDB_PASSWORD}".encode()
        ).decode()

        # --- Embeddings ---
        # Provider: "ollama", "openrouter", "openai", "custom"
        self.EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "ollama")
        self.EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", self._default_model())
        self.EMBEDDING_API_KEY = self._resolve_api_key()
        self.EMBEDDING_URL = self._resolve_url()
        self.EMBEDDING_DIMS = int(os.getenv("EMBEDDING_DIMS", self._default_dims()))
        self.EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "20"))

        # --- Brain Inbox ---
        self.BRAIN_INBOX = os.getenv(
            "BRAIN_INBOX", str(Path.home() / "brain-inbox")
        )

    def _default_model(self):
        defaults = {
            "ollama": "nomic-embed-text",
            "openrouter": "qwen/qwen3-embedding-8b",
            "openai": "text-embedding-3-small",
        }
        return defaults.get(self.EMBEDDING_PROVIDER, "nomic-embed-text")

    def _resolve_api_key(self):
        """Resolve API key from provider-specific or generic env var."""
        provider_keys = {
            "openrouter": "OPENROUTER_API_KEY",
            "openai": "OPENAI_API_KEY",
            "custom": "CUSTOM_API_KEY",
        }
        specific = provider_keys.get(self.EMBEDDING_PROVIDER)
        if specific:
            return os.getenv(specific, os.getenv("EMBEDDING_API_KEY", ""))
        return ""

    def _resolve_url(self):
        """Resolve embedding URL from provider-specific or generic env var."""
        if self.EMBEDDING_PROVIDER == "custom":
            return os.getenv("CUSTOM_EMBEDDING_URL", os.getenv("EMBEDDING_URL", ""))
        if self.EMBEDDING_PROVIDER == "ollama":
            return os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/embeddings"
        return os.getenv("EMBEDDING_URL", self._default_url())

    def _default_url(self):
        defaults = {
            "ollama": "http://localhost:11434/api/embeddings",
            "openrouter": "https://openrouter.ai/api/v1/embeddings",
            "openai": "https://api.openai.com/v1/embeddings",
        }
        return defaults.get(self.EMBEDDING_PROVIDER, "http://localhost:11434/api/embeddings")

    def _default_dims(self):
        defaults = {
            "ollama": "768",
            "openrouter": "1024",
            "openai": "1536",
        }
        return defaults.get(self.EMBEDDING_PROVIDER, "768")

    def get_embedding(self, texts):
        """
        Generate embeddings for a list of texts.
        Returns list of float vectors, or None on failure.
        """
        import json
        import urllib.request
        import urllib.error

        if self.EMBEDDING_PROVIDER == "ollama":
            return self._embed_ollama(texts)
        else:
            return self._embed_api(texts)

    def _embed_ollama(self, texts):
        """Ollama embedding — one text at a time (Ollama API limitation)."""
        import json
        import urllib.request

        results = []
        for text in texts:
            payload = json.dumps({
                "model": self.EMBEDDING_MODEL,
                "prompt": text
            }).encode()
            req = urllib.request.Request(
                self.EMBEDDING_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    d = json.loads(resp.read())
                results.append(d["embedding"])
            except Exception as e:
                print(f"  Ollama embedding error: {e}")
                return None
        return results

    def _embed_api(self, texts):
        """OpenAI-compatible embedding API (OpenRouter, OpenAI, etc.)."""
        import json
        import urllib.request
        import urllib.error

        if not self.EMBEDDING_API_KEY:
            raise ValueError(
                f"EMBEDDING_API_KEY is required for provider '{self.EMBEDDING_PROVIDER}'. "
                "Set it in .env or as an environment variable."
            )

        payload = json.dumps({
            "model": self.EMBEDDING_MODEL,
            "input": texts,
        }).encode()
        req = urllib.request.Request(
            self.EMBEDDING_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.EMBEDDING_API_KEY}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                d = json.loads(resp.read())
            return [item["embedding"] for item in d["data"]]
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"  API error {e.code}: {body[:200]}")
            return None
        except Exception as e:
            print(f"  Embedding error: {e}")
            return None

    def arcadedb_query(self, sql):
        """Execute a read-only query against ArcadeDB via MCP."""
        import json
        import urllib.request

        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "query", "arguments": {
                "database": self.ARCADEDB_DATABASE,
                "language": "sql",
                "query": sql,
            }},
        }).encode()
        req = urllib.request.Request(self.ARCADEDB_URL, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {self.ARCADEDB_AUTH}",
        })
        with urllib.request.urlopen(req) as resp:
            d = json.loads(resp.read())
        return json.loads(d["result"]["content"][0]["text"])["records"]

    def arcadedb_execute(self, sql):
        """Execute a write command against ArcadeDB via MCP."""
        import json
        import urllib.request

        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "execute_command", "arguments": {
                "database": self.ARCADEDB_DATABASE,
                "language": "sql",
                "command": sql,
            }},
        }).encode()
        req = urllib.request.Request(self.ARCADEDB_URL, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {self.ARCADEDB_AUTH}",
        })
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())


# Singleton — import this
cfg = Config()
