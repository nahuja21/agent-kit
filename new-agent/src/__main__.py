"""Entry point for the Project Summary Agent."""

import asyncio
import sys

from src.console import ConsoleApp
from src.console.app import run_console


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(run_console())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)


if __name__ == "__main__":
    main()
