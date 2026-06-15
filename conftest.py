"""Put the repository root on sys.path so tests can import BotWClient.* directly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
