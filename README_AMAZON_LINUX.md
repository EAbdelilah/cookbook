# Running Eswap Strategic Writing Assistant on Amazon Linux

This guide provides step-by-step instructions for setting up and running the `eswap_assistant.py` script on an Amazon Linux (AL2 or AL2023) instance.

## 1. Connect to your Amazon Linux Instance

SSH into your instance:
```bash
ssh -i your-key.pem ec2-user@your-instance-public-ip
```

## 2. Update the System

Ensure your package manager is up to date:
```bash
sudo yum update -y
```

## 3. Install Python 3 and Development Tools

Most Amazon Linux instances come with Python 3 pre-installed. Verify it:
```bash
python3 --version
```

If not installed, install it:
```bash
sudo yum install python3 -y
```

## 4. Set Up a Virtual Environment (Recommended)

Using a virtual environment keeps your global Python installation clean.

```bash
# Create the environment
python3 -m venv eswap-env

# Activate it
source eswap-env/bin/activate
```

## 5. Install Dependencies

Install the required libraries using the provided `requirements.txt`:
```bash
pip install -r requirements.txt
```

## 6. Create the Script File

You can use the `nano` text editor to create and save the script file on your instance.

1.  **Open nano:**
    ```bash
    nano eswap_assistant.py
    ```
2.  **Paste the content:** Copy the script code from your local machine and paste it into the terminal (usually right-click or `Ctrl+Shift+V`).
3.  **Save and Exit:**
    - Press `Ctrl + O` (then `Enter`) to write the file.
    - Press `Ctrl + X` to exit the editor.

## 7. Configure your API Key

For security, it is best to use an environment variable.

### Set the Environment Variable
Set it in your current terminal session:
```bash
export GEMINI_API_KEY="your_actual_api_key_here"
```

To make it persistent, add the line above to your `~/.bashrc` file.

## 8. Run the Assistant

Start the script:
```bash
python3 eswap_assistant.py
```

## Troubleshooting

- **Rate Limits:** The script has built-in delays (4 seconds between calls) to stay within the Gemini free tier. If you hit limits, it will automatically wait and retry.
- **Model Name:** The script uses `gemini-1.5-flash`. Ensure your API key has access to this model.
- **Network Access:** Ensure your EC2 instance has outbound internet access (port 443) to reach Google's API endpoints and search.
