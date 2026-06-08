# THE MASTER FIX FOR AMAZON LINUX

Follow these exact steps to fix the Python version warnings and missing module errors.

## 1. Install Python 3.11
```bash
# For AL2023:
sudo yum install python3.11 -y

# For Amazon Linux 2 (if the above fails):
sudo amazon-linux-extras install python3.11 -y
```

## 2. Clean Setup of the environment
```bash
# Remove the old environment if it exists
rm -rf eswap-env

# Create a fresh environment with Python 3.11
python3.11 -m venv eswap-env

# Activate it
source eswap-env/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install google-genai python-telegram-bot googlesearch-python
```

## 3. Create/Update the Script
Use `nano eswap_assistant.py` to paste the modern script provided in the previous message.

## 4. Set your Keys
```bash
export GEMINI_API_KEY="PASTE_YOUR_KEY_HERE"
export TELEGRAM_BOT_TOKEN="PASTE_YOUR_BOT_TOKEN_HERE"
```

## 5. Run it
```bash
python3 eswap_assistant.py
```

---

### Why this fixes it:
1. **No module named 'google'**: This happened because you were likely trying to run the script outside your virtual environment.
2. **No module named 'telegram'**: This happened because `python-telegram-bot` was not installed in your active environment.
3. **Python 3.9 Warnings**: Moving to Python 3.11 stops the "End of Life" warnings from Google's libraries.
