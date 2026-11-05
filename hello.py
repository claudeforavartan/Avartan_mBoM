"""A simple starter script to check that the Python environment works."""

import platform
import sys


def greet(name: str = "World") -> str:
    """Return a friendly greeting."""
    return f"Hello, {name}! Welcome to Aditya_mBoM."


def main() -> None:
    print(greet())
    print(f"Python version: {sys.version.split()[0]}")
    print(f"Running on: {platform.system()} {platform.release()}")


if __name__ == "__main__":
    main()
