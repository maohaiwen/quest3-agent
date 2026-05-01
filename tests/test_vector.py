"""Vector database testing utilities"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.vector_service import VectorService
from app.config import settings


class VectorDatabaseTester:
    """Vector database testing utilities for querying vector data"""

    def __init__(self):
        """Initialize vector database tester"""
        self.vector_service = VectorService()

    def list_all_collections(self):
        """List all collections in vector database"""
        print("\n=== All Vector Collections ===")

        if not self.vector_service.is_available():
            print("Vector store not available")
            return []

        try:
            collections = self.vector_service.client.list_collections()
            print(f"Found {len(collections)} collection(s):")

            for i, collection in enumerate(collections, 1):
                print(f"\nCollection {i}:")
                print(f"  Name: {collection.name}")
                print(f"  ID: {collection.id}")

                # Get count
                count = collection.count()
                print(f"  Document Count: {count}")

            return collections

        except Exception as e:
            print(f"Error listing collections: {e}")
            return []

    def get_collection_documents(self, session_id: str):
        """Get all documents from a session's collection

        Args:
            session_id: Session ID (collection name will be session_{session_id})
        """
        print(f"\n=== Documents for Session {session_id} ===")

        if not self.vector_service.is_available():
            print("Vector store not available")
            return []

        try:
            documents = self.vector_service.get_all(session_id)

            if not documents:
                print(f"No documents found for session {session_id}")
                return []

            print(f"Found {len(documents)} document(s):")

            for i, doc in enumerate(documents, 1):
                print(f"\nDocument {i}:")
                print(f"  ID: {doc['id']}")
                print(f"  Content: {doc['content'][:300]}{'...' if len(doc['content']) > 300 else ''}")
                print(f"  Metadata: {doc['metadata']}")

            return documents

        except Exception as e:
            print(f"Error getting documents: {e}")
            return []

    def search_collection(self, session_id: str, query: str, n_results: int = 5):
        """Search a collection for relevant content

        Args:
            session_id: Session ID
            query: Search query
            n_results: Number of results
        """
        print(f"\n=== Search Results for: '{query}' ===")

        if not self.vector_service.is_available():
            print("Vector store not available")
            return []

        try:
            results = self.vector_service.search(session_id, query, n_results)

            if not results:
                print("No results found")
                return []

            print(f"Found {len(results)} result(s):")

            for i, result in enumerate(results, 1):
                print(f"\nResult {i}:")
                print(f"  Distance: {result['distance']:.4f}")
                print(f"  Content: {result['content'][:300]}{'...' if len(result['content']) > 300 else ''}")
                print(f"  Metadata: {result['metadata']}")

            return results

        except Exception as e:
            print(f"Error searching: {e}")
            return []

    def delete_document(self, session_id: str, doc_id: str):
        """Delete a document from collection

        Args:
            session_id: Session ID
            doc_id: Document ID
        """
        print(f"\n=== Deleting Document {doc_id} ===")

        if not self.vector_service.is_available():
            print("Vector store not available")
            return False

        try:
            # First show the document
            documents = self.vector_service.get_all(session_id)
            doc = next((d for d in documents if d['id'] == doc_id), None)

            if doc:
                print(f"Document content: {doc['content'][:200]}")
                confirm = input("\nDelete this document? (yes/no): ").strip().lower()
                if confirm != 'yes':
                    print("Deletion cancelled")
                    return False
            else:
                print(f"Document {doc_id} not found")
                return False

            result = self.vector_service.delete(session_id, doc_id)

            if result:
                print(f"Document {doc_id} deleted successfully")
            else:
                print(f"Failed to delete document {doc_id}")

            return result

        except Exception as e:
            print(f"Error deleting document: {e}")
            return False

    def add_test_document(self, session_id: str, content: str, metadata: dict = None):
        """Add a test document to collection

        Args:
            session_id: Session ID
            content: Content to add
            metadata: Optional metadata
        """
        print(f"\n=== Adding Document to Session {session_id} ===")

        if not self.vector_service.is_available():
            print("Vector store not available")
            return None

        try:
            doc_id = self.vector_service.add(session_id, content, metadata)
            print(f"Document added with ID: {doc_id}")
            print(f"Content: {content[:200]}{'...' if len(content) > 200 else ''}")
            return doc_id

        except Exception as e:
            print(f"Error adding document: {e}")
            return None

    def clear_collection(self, session_id: str, confirm: bool = False):
        """Clear all documents from a collection

        Args:
            session_id: Session ID
            confirm: Confirmation flag
        """
        print(f"\n=== Clearing Collection for Session {session_id} ===")

        if not self.vector_service.is_available():
            print("Vector store not available")
            return False

        try:
            collection = self.vector_service.get_or_create_collection(session_id)
            count = collection.count()

            if count == 0:
                print("Collection is already empty")
                return False

            print(f"Collection contains {count} document(s)")

            if not confirm:
                response = input("Are you sure? Type 'yes' to confirm: ")
                if response.lower() != 'yes':
                    print("Clear cancelled")
                    return False

            # Delete all documents by getting all IDs
            results = collection.get()
            if results['ids']:
                collection.delete(ids=results['ids'])

            print(f"Collection cleared successfully")
            return True

        except Exception as e:
            print(f"Error clearing collection: {e}")
            return False

    def get_vector_store_info(self):
        """Get vector store information"""
        print("\n=== Vector Store Information ===")

        if not self.vector_service.is_available():
            print("Vector store not available")
            return {}

        try:
            info = {
                "persist_directory": self.vector_service.persist_directory,
                "dimension": self.vector_service.dimension,
                "client_available": self.vector_service.client is not None
            }

            print(f"Persist Directory: {info['persist_directory']}")
            print(f"Vector Dimension: {info['dimension']}")
            print(f"Client Available: {info['client_available']}")

            # List collections
            collections = self.vector_service.client.list_collections()
            total_docs = sum(c.count() for c in collections)

            print(f"Total Collections: {len(collections)}")
            print(f"Total Documents: {total_docs}")

            return info

        except Exception as e:
            print(f"Error getting info: {e}")
            return {}


def main():
    """Main testing function"""
    tester = VectorDatabaseTester()

    print("Vector Database Testing Utilities")
    print("=" * 50)
    print("\nAvailable commands:")
    print("1. List all collections")
    print("2. Get collection documents")
    print("3. Search collection")
    print("4. Add test document")
    print("5. Delete document")
    print("6. Clear collection")
    print("7. Get vector store info")
    print("0. Exit")

    while True:
        choice = input("\nEnter command number: ").strip()

        if choice == "0":
            print("Exiting...")
            break

        elif choice == "1":
            tester.list_all_collections()

        elif choice == "2":
            session_id = input("Enter session ID: ").strip()
            tester.get_collection_documents(session_id)

        elif choice == "3":
            session_id = input("Enter session ID: ").strip()
            query = input("Enter search query: ").strip()
            n_results = input("Enter number of results (default 5): ").strip()
            n_results = int(n_results) if n_results else 5
            tester.search_collection(session_id, query, n_results)

        elif choice == "4":
            session_id = input("Enter session ID: ").strip()
            content = input("Enter content: ").strip()
            tester.add_test_document(session_id, content)

        elif choice == "5":
            session_id = input("Enter session ID: ").strip()
            doc_id = input("Enter document ID: ").strip()
            tester.delete_document(session_id, doc_id)

        elif choice == "6":
            session_id = input("Enter session ID: ").strip()
            tester.clear_collection(session_id)

        elif choice == "7":
            tester.get_vector_store_info()

        else:
            print("Invalid command")


if __name__ == "__main__":
    main()
