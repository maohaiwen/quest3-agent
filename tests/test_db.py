"""Database testing utilities"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.connection import DatabaseConnection
from app.database.repositories import SessionRepository, MessageRepository, MemoryRepository
from app.config import settings


class DatabaseTester:
    """Database testing utilities for querying data"""

    def __init__(self):
        """Initialize database tester"""
        self.db = DatabaseConnection(settings.DATABASE_URL)
        self.session_repo = SessionRepository(self.db)
        self.message_repo = MessageRepository(self.db)
        self.memory_repo = MemoryRepository(self.db)

    async def initialize(self):
        """Initialize database connection"""
        await self.db.connect()

    async def close(self):
        """Close database connection"""
        await self.db.disconnect()

    async def list_all_sessions(self):
        """List all sessions in the database"""
        print("\n=== All Sessions ===")
        try:
            # Direct query to get all sessions
            sql = "SELECT * FROM sessions ORDER BY created_at DESC"
            rows = await self.db.fetch_all(sql)

            if not rows:
                print("No sessions found")
                return []

            sessions = []
            for row in rows:
                # Count messages for each session
                count_sql = "SELECT COUNT(*) as count FROM messages WHERE session_id = ?"
                count_row = await self.db.fetch_one(count_sql, (row["id"],))
                message_count = count_row["count"] if count_row else 0

                session_info = {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "title": row["title"],
                    "status": row["status"],
                    "message_count": message_count,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
                sessions.append(session_info)

            for i, session in enumerate(sessions, 1):
                print(f"\nSession {i}:")
                print(f"  ID: {session['id']}")
                print(f"  User ID: {session['user_id']}")
                print(f"  Title: {session['title']}")
                print(f"  Status: {session['status']}")
                print(f"  Message Count: {session['message_count']}")
                print(f"  Created: {session['created_at']}")
                print(f"  Updated: {session['updated_at']}")

            return sessions

        except Exception as e:
            print(f"Error listing sessions: {e}")
            return []

    async def get_session_messages(self, session_id: str, limit: int = None):
        """Get all messages for a session

        Args:
            session_id: Session ID
            limit: Optional limit on number of messages
        """
        print(f"\n=== Messages for Session {session_id} ===")

        session = await self.session_repo.get(session_id)
        if not session:
            print(f"Session {session_id} not found")
            return []

        print(f"Session: {session.title} (Status: {session.status})")

        messages = await self.message_repo.get_by_session(session_id, limit or 1000)

        if not messages:
            print("No messages found")
            return []

        for i, msg in enumerate(messages, 1):
            print(f"\nMessage {i}:")
            print(f"  ID: {msg.id}")
            print(f"  Role: {msg.role.value}")
            print(f"  Content: {msg.content[:200]}{'...' if len(msg.content) > 200 else ''}")
            print(f"  Created: {msg.created_at}")

        return messages

    async def get_session_memory(self, session_id: str):
        """Get all memory entries for a session

        Args:
            session_id: Session ID
        """
        print(f"\n=== Memory for Session {session_id} ===")

        memories = await self.memory_repo.get_by_session(session_id)

        if not memories:
            print("No memories found")
            return []

        for i, mem in enumerate(memories, 1):
            print(f"\nMemory {i}:")
            print(f"  ID: {mem['id']}")
            print(f"  Session ID: {mem['session_id']}")
            print(f"  Content: {mem['content'][:200]}{'...' if len(mem['content']) > 200 else ''}")
            print(f"  Metadata: {mem['metadata']}")
            print(f"  Created: {mem['created_at']}")

        return memories

    async def search_sessions_by_title(self, keyword: str):
        """Search sessions by title

        Args:
            keyword: Search keyword
        """
        print(f"\n=== Sessions matching '{keyword}' ===")

        sql = "SELECT * FROM sessions WHERE title LIKE ? ORDER BY created_at DESC"
        rows = await self.db.fetch_all(sql, (f"%{keyword}%",))

        if not rows:
            print("No matching sessions found")
            return []

        for i, row in enumerate(rows, 1):
            print(f"\nSession {i}:")
            print(f"  ID: {row['id']}")
            print(f"  Title: {row['title']}")
            print(f"  Status: {row['status']}")
            print(f"  Created: {row['created_at']}")

        return rows

    async def get_database_stats(self):
        """Get database statistics"""
        print("\n=== Database Statistics ===")

        try:
            # Count sessions
            session_count = await self.db.fetch_one("SELECT COUNT(*) as count FROM sessions")
            print(f"Total Sessions: {session_count['count']}")

            # Count messages
            message_count = await self.db.fetch_one("SELECT COUNT(*) as count FROM messages")
            print(f"Total Messages: {message_count['count']}")

            # Count memories
            memory_count = await self.db.fetch_one("SELECT COUNT(*) as count FROM memory")
            print(f"Total Memories: {memory_count['count']}")

            # Get database file size
            db_path = Path(settings.DATABASE_URL.replace("sqlite+aiosqlite:///", ""))
            if db_path.exists():
                size_mb = db_path.stat().st_size / (1024 * 1024)
                print(f"Database File Size: {size_mb:.2f} MB")
                print(f"Database Path: {db_path.absolute()}")

            return {
                "sessions": session_count['count'],
                "messages": message_count['count'],
                "memories": memory_count['count']
            }

        except Exception as e:
            print(f"Error getting stats: {e}")
            return {}

    async def delete_session(self, session_id: str, confirm: bool = False):
        """Delete a session and all its data

        Args:
            session_id: Session ID
            confirm: Confirmation flag
        """
        if not confirm:
            print(f"\n⚠️  WARNING: This will delete session {session_id}")
            response = input("Are you sure? Type 'yes' to confirm: ")
            if response.lower() != 'yes':
                print("Deletion cancelled")
                return False

        # Delete messages
        await self.db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))

        # Delete memories
        await self.db.execute("DELETE FROM memory WHERE session_id = ?", (session_id,))

        # Delete session
        result = await self.session_repo.delete(session_id)

        await self.db.commit()

        print(f"Session {session_id} deleted successfully")
        return True


async def main():
    """Main testing function"""
    tester = DatabaseTester()

    try:
        await tester.initialize()

        print("Database Testing Utilities")
        print("=" * 50)
        print("\nAvailable commands:")
        print("1. List all sessions")
        print("2. Get session messages")
        print("3. Get session memory")
        print("4. Search sessions by title")
        print("5. Get database statistics")
        print("6. Delete session")
        print("0. Exit")

        while True:
            choice = input("\nEnter command number: ").strip()

            if choice == "0":
                print("Exiting...")
                break

            elif choice == "1":
                await tester.list_all_sessions()

            elif choice == "2":
                session_id = input("Enter session ID: ").strip()
                limit = input("Enter message limit (or press Enter for all): ").strip()
                limit = int(limit) if limit else None
                await tester.get_session_messages(session_id, limit)

            elif choice == "3":
                session_id = input("Enter session ID: ").strip()
                await tester.get_session_memory(session_id)

            elif choice == "4":
                keyword = input("Enter search keyword: ").strip()
                await tester.search_sessions_by_title(keyword)

            elif choice == "5":
                await tester.get_database_stats()

            elif choice == "6":
                session_id = input("Enter session ID to delete: ").strip()
                await tester.delete_session(session_id)

            else:
                print("Invalid command")

    finally:
        await tester.close()


if __name__ == "__main__":
    asyncio.run(main())
