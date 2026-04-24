# Running Eswap Assistant on Amazon Linux

This guide addresses the Python 3.9 deprecation and Telegram module errors.

## 1. Install Python 3.11+ (Recommended)

Amazon Linux 2 and AL2023 often default to Python 3.9. To avoid "End of Life" warnings:

### For AL2023:
```bash
sudo yum install python3.11 -y
```

### For Amazon Linux 2:
```bash
sudo amazon-linux-extras install python3.11 -y
```

## 2. Set Up a New Virtual Environment

If you have an old environment, it's best to start fresh with the new Python version.

```bash
# Create environment with Python 3.11
python3.11 -m venv eswap-env

# Activate it
source eswap-env/bin/activate
```

## 3. Install Modern Dependencies

The new script uses the latest `google-genai` and `python-telegram-bot` libraries.

```bash
pip install -r requirements.txt
```

## 4. Set Up Environment Variables

Avoid editing the script. Set your tokens in the terminal:

```bash
export GEMINI_API_KEY="your_gemini_key_here"
export TELEGRAM_BOT_TOKEN="your_telegram_bot_token_here"
```

## 5. Run the Assistant

```bash
python3 eswap_assistant.py
```

- If `TELEGRAM_BOT_TOKEN` is set, it starts as a Telegram Bot.
- If not set, it runs in CLI mode.

## Troubleshooting "ModuleNotFoundError: No module named 'telegram'"

This error happens when:
1. You installed the library but are NOT in the virtual environment. Ensure you see `(eswap-env)` in your prompt.
2. You installed it in a different Python version's environment.

**Fix:**
```bash
source eswap-env/bin/activate
pip install python-telegram-bot
```
