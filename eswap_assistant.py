import os
import json
import re
import time
import random
import asyncio
from typing import List, Dict, Any, Optional

# Dependencies
# pip install google-genai python-telegram-bot googlesearch-python
from google import genai
from google.genai import types
from googlesearch import search

# Try importing telegram
try:
    from telegram import Update
    from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

# --- CONFIGURATION ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- KNOWLEDGE BASE (RESTORED) ---

PITCH_DECK_CONTEXT = """
DOCUMENT: Eswap Pitch Deck Summary
THE PROBLEM: The $4 trillion Islamic finance market is locked out of DeFi leverage due to forbidden interest (Riba).
THE PRODUCT & SOLUTION: A 0% interest rate, transparent, and efficient Decentralized Exchange (DEX). Guaranteed Sharia compliance.
COMPETITIVE ADVANTAGE: Unique positioning in an under-exploited segment. First Sharia-compliant DEX with short selling.
TRACTION & ROADMAP: Funds Raised: $250,000. MVP is live on testnet (Q3 2025). Mainnet launch in Q1 2026.
TEAM: Abdelilah Essaih (CEO), Samir Moreira Antonio (Co-Founder), Jean-Christophe Bougnet (Co-Founder).
"""

BUSINESS_MODEL_CANVAS_CONTEXT = """
DOCUMENT: BUSINESS MODEL CANVAS: Eswap
KEY PARTNERS: 0x, Uniswap, Polygon/Arbitrum, Chainlink.
VALUE PROPOSITION: Fixed & Predictable Cost (single 1% fee). Authentic Shariah Compliance.
CUSTOMER SEGMENTS: Pious Retail Investor, Long-Term Secular Investor, Strategic Hedger.
REVENUE STREAMS: Primary: 1% transaction fee on total notional value.
"""

COMPETITIVE_LANDSCAPE_CONTEXT = """
DOCUMENT: Halal DEX Landscape Analysis
COMPETITORS: MRHB DeFi (Marhaba), Haqq Network Ecosystem, Kanz Finance, Caizchain.
STRATEGIC GAPS: 1. Liquidity Gap, 2. Technology Gap, 3. Trust Gap.
"""

INVESTMENT_THESIS_CONTEXT = """
DOCUMENT: Master Market Research & Investment Thesis
THE CORE THESIS: Eswap's 1% fee is its greatest strategic asset. Cheaper than competitors after ~30 days.
HOLDING PERIOD COST COMPARISON ($10k position):
- 30 Days: Eswap ($100), Competitor ($100).
- 180 Days: Eswap ($100), Competitor ($550).
"""

MARKETING_STRATEGY_CONTEXT = """
DOCUMENT: Eswap Marketing Strategy Plan
TARGET AUDIENCE: Primary (60%) Pious Retail Investors, Secondary (30%) Long-Term Secular Investors.
MESSAGING: For Halal: "Unlock DeFi leverage without compromising your faith." For Secular: "Fixed fee beats variable funding rates."
"""

USER_ACQUISITION_WALLET_PLAN_CONTEXT = """
DOCUMENT: Distribution & User Acquisition Plan (Leveraging Wallets)
TARGET WALLETS: MetaMask, Trust Wallet, Coin98, TokenPocket, Ledger.
GOAL: 25,000 users in Year 1.
"""

DOCUMENTS = {
    "1": ("PITCH_DECK", PITCH_DECK_CONTEXT),
    "2": ("BUSINESS_MODEL", BUSINESS_MODEL_CANVAS_CONTEXT),
    "3": ("COMPETITION", COMPETITIVE_LANDSCAPE_CONTEXT),
    "4": ("THESIS", INVESTMENT_THESIS_CONTEXT),
    "5": ("MARKETING", MARKETING_STRATEGY_CONTEXT),
    "6": ("WALLETS", USER_ACQUISITION_WALLET_PLAN_CONTEXT),
}

DOCUMENT_DESCRIPTIONS = {
    "1": "Investor pitch deck: problem, solution, traction, team, roadmap.",
    "2": "Business Model: partners, segments, 1% fee revenue model.",
    "3": "Competition: MRHB, Haqq, and gaps in the market.",
    "4": "Investment Thesis: Break-even analysis vs daily funding rates.",
    "5": "Marketing: Audience segmentation and key messaging.",
    "6": "Wallet Plan: Growth via MetaMask and Trust Wallet integrations.",
}

METRICS = {
    "funding_raised_usd": 250000,
    "seed_round_target_usd": 1500000,
    "user_target_y1": 25000,
    "mainnet_launch": "Q1 2026",
    "transaction_fee_percent": 1
}

# --- AI AGENTS ---

class EswapAssistant:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.model_id = "gemini-1.5-flash"

    async def make_api_call(self, prompt: str, system_instruction: str, retries: int = 3) -> str:
        for attempt in range(retries):
            await asyncio.sleep(4)
            try:
                response = self.client.models.generate_content(
                    model=self.model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction
                    )
                )
                return response.text
            except Exception as e:
                if ("429" in str(e) or "quota" in str(e).lower()) and attempt < retries - 1:
                    wait_time = 60 + random.uniform(1, 5)
                    print(f"[Warning] Rate limit. Attempt {attempt+1}/{retries}. Waiting {wait_time:.2f}s...")
                    await asyncio.sleep(wait_time)
                else:
                    return f"API Error: {e}"
        return "Error: Max retries exceeded."

    async def librarian_ai(self, user_query: str, search_summary: str) -> List[str]:
        """Selects relevant document IDs."""
        descriptions = "\n".join([f"{k}: {v}" for k, v in DOCUMENT_DESCRIPTIONS.items()])
        prompt = (
            f"USER QUERY: {user_query}\n\n"
            f"SEARCH SUMMARY: {search_summary}\n\n"
            f"DOCUMENTS:\n{descriptions}\n\n"
            "Return ONLY a comma-separated list of document IDs relevant to the query. Example: 1, 4"
        )
        resp = await self.make_api_call(prompt, "You are a librarian routing queries to the right internal documents.")
        return re.findall(r'\d+', resp)

    async def searcher_ai(self, user_query: str) -> str:
        print(f"... [Searcher AI] Searching for: {user_query}")
        try:
            results = list(search(user_query, num_results=3))
            formatted = "\n".join([f"- {r}" for r in results])
            summary_prompt = f"Summarize these search results for query '{user_query}':\n{formatted}"
            return await self.make_api_call(summary_prompt, "You are a research assistant.")
        except Exception as e:
            return f"Search context unavailable: {e}"

    async def generate_final_answer(self, user_query: str, search_summary: str) -> str:
        # 1. Routing
        doc_ids = await self.librarian_ai(user_query, search_summary)
        context = ""
        for d_id in doc_ids:
            if d_id in DOCUMENTS:
                name, content = DOCUMENTS[d_id]
                context += f"\n--- {name} ---\n{content}\n"

        # 2. Adaptive Persona
        is_sharia = any(k in user_query.lower() for k in ["sharia", "halal", "islamic", "riba"])
        if is_sharia:
            persona = "Expert in Sharia-compliant finance. Use terms like 'halal' and 'riba-free'."
        else:
            persona = "Ethical finance expert. Use secular terms like '0% interest' and 'fixed-fee'. Avoid Sharia jargon unless quoting documents."

        system_instruction = (
            f"You are Eswap's Strategic Assistant. Persona: {persona}. "
            "Synthesize internal documents, metrics, and web search results into a polished, definitive answer."
        )

        full_prompt = (
            f"INTERNAL CONTEXT:\n{context}\n\n"
            f"METRICS:\n{json.dumps(METRICS, indent=2)}\n\n"
            f"WEB SEARCH:\n{search_summary}\n\n"
            f"QUESTION: {user_query}"
        )

        print("... [Writer AI] Generating final response")
        return await self.make_api_call(full_prompt, system_instruction)

# --- BOT HANDLERS ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    assistant = context.application.bot_data['assistant']

    await update.message.reply_text("Processing your request with Eswap AI agents...")

    search_summary = await assistant.searcher_ai(user_text)
    answer = await assistant.generate_final_answer(user_text, search_summary)

    await update.message.reply_text(answer)

async def start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salaam! I am the Eswap Strategic Assistant. Ask me anything about Eswap's mission, tokenomics, or roadmap.")

# --- RUNNERS ---

def run_cli(assistant: EswapAssistant):
    print("\n--- Eswap CLI Assistant (Full RAG Mode) ---")
    while True:
        query = input("\nYour Question (or 'exit'): ")
        if query.lower() == 'exit': break

        async def execute():
            search_summary = await assistant.searcher_ai(query)
            answer = await assistant.generate_final_answer(query, search_summary)
            print(f"\nANSWER:\n{answer}")

        asyncio.run(execute())

def main():
    if not GEMINI_API_KEY:
        print("FATAL: GEMINI_API_KEY environment variable is required.")
        return

    assistant = EswapAssistant(GEMINI_API_KEY)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_AVAILABLE:
        print("Starting Eswap Telegram Bot...")
        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        app.bot_data['assistant'] = assistant
        app.add_handler(CommandHandler("start", start_bot))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        app.run_polling()
    else:
        run_cli(assistant)

if __name__ == "__main__":
    main()
