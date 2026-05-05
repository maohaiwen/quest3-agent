"""Vector storage service for long-term memory"""
import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import Optional, List, Dict, Any
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class VectorService:
    """Service for managing vector storage using ChromaDB"""

    def __init__(self, persist_directory: Optional[str] = None):
        """Initialize vector service

        Args:
            persist_directory: Directory to persist vector store
        """
        self.persist_directory = persist_directory or "./chroma_db"
        self.dimension = settings.MEMORY_VECTOR_DIMENSION

        try:
            self.client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=ChromaSettings(
                    anonymized_telemetry=True
                )
            )
            logger.info(f"Vector store initialized at {self.persist_directory}")
        except Exception as e:
            logger.error(f"Error initializing vector store: {e}")
            self.client = None

    def get_or_create_collection(self, agent_id: str):
        """Get or create collection for agent

        Args:
            agent_id: Agent ID

        Returns:
            ChromaDB collection
        """
        if not self.client:
            raise ValueError("Vector store not initialized")

        try:
            return self.client.get_or_create_collection(
                name=f"agent_{agent_id}",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            logger.error(f"Error getting collection: {e}")
            raise

    def add(
        self,
        agent_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add content to vector store

        Args:
            agent_id: Agent ID
            content: Content to store
            metadata: Optional metadata

        Returns:
            Document ID
        """
        import uuid

        if not self.client:
            raise ValueError("Vector store not initialized")

        collection = self.get_or_create_collection(agent_id)

        doc_id = str(uuid.uuid4())

        try:
            collection.add(
                documents=[content],
                ids=[doc_id],
                metadatas=[metadata or {}]
            )
            return doc_id
        except Exception as e:
            logger.error(f"Error adding to vector store: {e}")
            raise

    def search(
        self,
        agent_id: str,
        query: str,
        n_results: int = 5
    ) -> List[Dict[str, Any]]:
        """Search vector store for relevant content

        Args:
            agent_id: Agent ID
            query: Search query
            n_results: Number of results to return

        Returns:
            List of search results
        """
        if not self.client:
            raise ValueError("Vector store not initialized")

        try:
            collection = self.get_or_create_collection(agent_id)
            results = collection.query(
                query_texts=[query],
                n_results=n_results
            )

            formatted_results = []
            if results and results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    formatted_results.append({
                        'content': doc,
                        'metadata': results['metadatas'][0][i] if results['metadatas'] else {},
                        'distance': results['distances'][0][i] if results['distances'] else 0
                    })

            return formatted_results

        except Exception as e:
            logger.error(f"Error searching vector store: {e}")
            return []

    def delete(self, agent_id: str, doc_id: str) -> bool:
        """Delete document from vector store

        Args:
            agent_id: Agent ID
            doc_id: Document ID

        Returns:
            True if deleted
        """
        if not self.client:
            raise ValueError("Vector store not initialized")

        try:
            collection = self.get_or_create_collection(agent_id)
            collection.delete(ids=[doc_id])
            return True
        except Exception as e:
            logger.error(f"Error deleting from vector store: {e}")
            return False

    def get_all(self, agent_id: str) -> List[Dict[str, Any]]:
        """Get all documents for agent

        Args:
            agent_id: Agent ID

        Returns:
            List of documents
        """
        if not self.client:
            raise ValueError("Vector store not initialized")

        try:
            collection = self.get_or_create_collection(agent_id)
            results = collection.get()

            formatted_results = []
            if results and results['documents']:
                for i, doc in enumerate(results['documents']):
                    formatted_results.append({
                        'id': results['ids'][i],
                        'content': doc,
                        'metadata': results['metadatas'][i] if results['metadatas'] else {}
                    })

            return formatted_results

        except Exception as e:
            logger.error(f"Error getting all from vector store: {e}")
            return []

    def is_available(self) -> bool:
        """Check if vector store is available

        Returns:
            True if available
        """
        return self.client is not None
