"""Root test configuration — set test environment variables before app modules are imported."""

import os

os.environ.setdefault("TRELLO_API_KEY", "test_key")
os.environ.setdefault("TRELLO_API_SECRET", "test_secret")
os.environ.setdefault("TRELLO_TOKEN", "test_token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test_anthropic_key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_bot_token")
os.environ.setdefault("TELEGRAM_SECRET", "test_telegram_secret")
os.environ.setdefault("WEBHOOK_BASE_URL", "https://test.example.com")
os.environ.setdefault("GITHUB_TOKEN", "test_github_token")
