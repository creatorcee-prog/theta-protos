"""`python -m server`: run the threaded dev server (PORT, default 8780)."""

from .app import serve

if __name__ == "__main__":
    serve()
