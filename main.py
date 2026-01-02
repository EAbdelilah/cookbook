import google.generativeai as genai
import json
import sys
import re
import os
import time
import random
from pathlib import Path
from googlesearch import search
import argparse
import PyPDF2
from pptx import Presentation

# --- File Reading Functions ---

def read_txt(file_path):
    """Reads text from a .txt file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def read_pdf(file_path):
    """Reads text from a .pdf file."""
    text = ""
    with open(file_path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text()
    return text

def read_pptx(file_path):
    """Reads text from a .pptx file."""
    text = ""
    prs = Presentation(file_path)
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                text += shape.text + "\n"
    return text

def load_documents_from_directory(dir_path):
    """Loads all supported documents from a directory and populates the global dictionaries."""
    global DOCUMENTS, DOCUMENT_DESCRIPTIONS
    DOCUMENTS = {}
    DOCUMENT_DESCRIPTIONS = {}
    doc_id = 1
    for filename in os.listdir(dir_path):
        file_path = os.path.join(dir_path, filename)
        content = ""
        if filename.endswith(".txt"):
            content = read_txt(file_path)
        elif filename.endswith(".pdf"):
            content = read_pdf(file_path)
        elif filename.endswith(".pptx"):
            content = read_pptx(file_path)

        if content:
            doc_key = str(doc_id)
            doc_name = os.path.splitext(filename)[0].upper()
            DOCUMENTS[doc_key] = (doc_name, content)
            # Create a simple description from the first 100 chars
            DOCUMENT_DESCRIPTIONS[doc_key] = f"{doc_name}: {content[:100]}..."
            doc_id += 1

    if not DOCUMENTS:
        print(f"[Warning] No documents found in '{dir_path}'. Using hardcoded knowledge base as fallback.")
        load_hardcoded_documents()

# --- CONFIGURATION ---
API_KEY = os.getenv("GEMINI_API_KEY")
if API_KEY:
    genai.configure(api_key=API_KEY)

# --- 1. PRE-LOADED KNOWLEDGE BASE (FROM YOUR DOCUMENTS) ---

# --- Document Dictionary & Descriptions for the "Librarian" AI ---
# These will be populated by load_documents_from_directory or load_hardcoded_documents
DOCUMENTS = {}
DOCUMENT_DESCRIPTIONS = {}

def load_hardcoded_documents():
    """Loads the original hardcoded documents as a fallback."""
    global DOCUMENTS, DOCUMENT_DESCRIPTIONS
    PITCH_DECK_CONTEXT = """
    DOCUMENT: Eswap Pitch Deck Summary

    THE PROBLEM:
    - The $4 trillion Islamic finance market is locked out of DeFi leverage due to forbidden interest (Riba), creating immense demand for a compliant solution.
    - There is an urgent need for a halal, transparent, and secure DEX for 1.9 billion Muslims.
    - No major competitor is 100% halal/sharia-compliant.
    - DEXs represent +35% of DeFi volume (~$20-30B/month in 2025).

    THE PRODUCT & SOLUTION:
    - A 0% interest rate, transparent, and efficient Decentralized Exchange (DEX).
    - Guaranteed Sharia compliance with automatic filtering of haram tokens (usury, gambling, etc.).
    - Deep liquidity sourced from 0x protocol/Uniswap.
    - A native token ($ESW) for governance and reduced fees (no interest).

    COMPETITIVE ADVANTAGE:
    - Unique positioning in an under-exploited segment combined with decentralized infrastructure leads to potential exponential growth.
    - We are the first Sharia-compliant DEX with short selling for crypto and tokenized RWAs.

    MARKET SIZE & PROJECTIONS:
    - Global DEX market monthly volume (2025): ~$60B.
    - Conservative user target: 500k to 1M users within 3 years.
    - Potential fee revenue: $15-20M/year.

    TRACTION & ROADMAP:
    - Funds Raised: $250,000 ($200k from Google Web3 accelerator, $50k from token sales).
    - MVP is live on testnet (Q3 2025).
    - Roadmap: Mainnet launch + audit in Q1 2026; Official Shariah board onboarding in Q2 2026.
    - Strategic Partners: Google Cloud, FasterCapital.
    - Web3 Partnerships: Bantgo, Div Protocol, Greeniz, Ari10, Metacard, Cleanchain, and Bitfinity.

    FUNDING NEEDS:
    - Seeking: $1.5M seed round.
    - Use of Funds: 40% dev & security, 25% legal & sharia certification, 20% targeted marketing (MENA & SEA), 15% treasury & audit.
    - Expected Return: Breakeven in 18 months with only 0.1% of DeFi volume captured.

    TEAM:
    - Abdelilah Essaih (CEO & Founder): Founder of a French startup specialized in blockchain engineering, one of the earliest in real estate tokenization in France.
    - Samir Moreira Antonio (Co-Founder & Senior Developer): Created Trainline application (10M+ downloads) & Hostelworld application (5M+ downloads).
    - Jean-Christophe Bougnet (Co-Founder & Developer): Previous Lead UI/UX developer at Deutsche Bank & Isabel Group with more than 1 million visitors each month.
    """

    BUSINESS_MODEL_CANVAS_CONTEXT = """
    DOCUMENT: BUSINESS MODEL CANVAS: Eswap

    KEY PARTNERS:
    - Liquidity Providers (Technology): 0x and Uniswap protocols to ensure deep liquidity from day one.
    - Technical Partners: L2 Blockchain (Polygon/Arbitrum), Price Oracles (Chainlink).
    - Marketing Partners: Influencers specializing in long-term investing and Islamic finance, Cryptohalal group.

    KEY ACTIVITIES:
    - Development & Maintenance: Continuous iteration on the Eswap protocol's smart contracts.
    - Marketing & Education: Creating content (articles, videos, calculators) to explain the advantage of the "Total Cost of Holding" versus funding rates.
    - Community Management: Engaging with and supporting the community on Twitter and Telegram.
    - Security: Conducting regular security audits and managing a bug bounty program.

    KEY RESOURCES:
    - Intangible: The source code of the Eswap protocol (Intellectual Property), the "Eswap" brand and its reputation, and the team's expertise in DeFi and Islamic finance.
    - Financial: Capital for development, marketing, and audits; The $ESW governance token and the protocol's treasury.

    VALUE PROPOSITION:
    - Problem Solved: Eswap opens up access to DeFi leverage for the $4T+ Islamic finance market. For all traders, it eliminates the unpredictable and corrosive cost of daily funding rates.
    - Competitive Advantage: 1. Fixed & Predictable Cost (single 1% fee). 2. Authentic Shariah Compliance. 3. Immediate Deep Liquidity (via 0x/Uniswap). 4. Alignment & Transparency (not a counterparty to users).

    CUSTOMER RELATIONSHIPS:
    - Interaction: Responsive support and education via Telegram, Twitter, and a blog/academy.
    - Loyalty Drivers: Loyalty by Principle (for the halal segment), Economic Retention (mathematically superior for long-term holds), and Aligned Interests (staking $ESW for revenue share).

    CHANNELS:
    - Main Channel: The Eswap decentralized application (dApp).
    - Acquisition Channels: Content Marketing, Social Media (Twitter, Telegram), Influencer Partnerships, and Public Relations.

    CUSTOMER SEGMENTS:
    1. The Pious Retail Investor: Crypto-educated users (MENA, Southeast Asia).
    2. The Long-Term Secular Investor: Sophisticated traders seeking a fixed-cost alternative to funding rates.
    3. The Strategic Hedger: Funds or individuals hedging spot portfolios at a predictable cost.
    4. (Future) Islamic Financial Institutions.

    COST STRUCTURE:
    - Team Salaries, Security Costs (audits, bug bounty), Marketing & Communication, Compliance Fees (legal, Shariah board), Operational Costs (infrastructure, gas fees).

    REVENUE STREAMS:
    - Primary: The single 1% transaction fee on the total notional value of each leveraged position.
    - Secondary: The Eswap token ($ESW).
    """

    COMPETITIVE_LANDSCAPE_CONTEXT = """
    DOCUMENT: Halal DEX Landscape Analysis

    EXECUTIVE SUMMARY:
    The global Sharia-compliant DEX market is nascent and highly fragmented. There is no dominant market leader. Existing platforms suffer from low liquidity, volume, and user adoption, failing to serve the 1.9 billion Muslim market. Liquidity is the primary hurdle. This analysis validates that a new DEX with superior technology, a clear liquidity strategy, and authentic Sharia governance can capture this market.

    LIVE & OPERATIONAL COMPETITORS:
    - MRHB DeFi (Marhaba): The most established "all-in-one" Halal DeFi ecosystem, but has not achieved significant scale. Trading volume is too low to be tracked by DeFiLlama, and its native token ($MRHB) market cap is low ($2-5M range).
    - Haqq Network Ecosystem: A well-funded, Sharia-compliant Layer 1 blockchain. Its DeFi ecosystem is in its infancy, with a TVL of only ~$1.6 million. There is a large gap between its high valuation (~$100M+ market cap for $ISLM) and its low on-chain activity.

    EMERGING & IN-DEVELOPMENT COMPETITORS:
    - Kanz Finance: A DEX focused on tokenizing Real World Assets (RWA) like sukuk (Islamic bonds). A highly differentiated but legally complex strategy.
    - Caizchain: A proposed Layer 1 "Islamic Blockchain," a direct competitor to Haqq but earlier in its development with less tangible progress.

    KEY STRATEGIC GAPS IN THE MARKET:
    1. The Liquidity Gap: No player has solved this. An innovative bootstrapping strategy is an immediate advantage.
    2. The Technology Gap: Existing platforms use standard AMM models. Advanced tech like zkProofs can create a product moat.
    3. The Trust Gap: Credibility is paramount. A new entrant needs a reputable Sharia board and security audits from day one.
    """

    INVESTMENT_THESIS_CONTEXT = """
    DOCUMENT: Master Market Research & Investment Thesis

    EXECUTIVE SUMMARY:
    The $4 trillion Islamic finance market and the multi-trillion dollar DeFi market operate in near-total isolation. Eswap solves this by offering a non-custodial, Shariah-compliant DEX on a scalable Layer-2. Its model is built on two pillars: a revolutionary 1% one-time fee structure that eliminates interest, and capital-efficient liquidity aggregation via 0x Protocol and Uniswap.

    THE CORE THESIS:
    Eswap's 1% fee is its greatest strategic asset. By reframing the value proposition from "transaction cost" to "Total Cost of Holding," Eswap becomes mathematically cheaper than any competitor for positions held over approximately 30 days. This positions Eswap to dominate the untapped Halal DeFi market and attract a niche of sophisticated secular traders. The Serviceable Obtainable Market (SOM) is projected to be $20M+ in annual revenue within 3-5 years.

    THE ESWAP ADVANTAGE (SIX PILLARS):
    1. Fixed-Fee Revolution: Absolute cost certainty.
    2. Aggregated Deep Liquidity: Solves the "cold start" problem.
    3. Authentic Shariah-compliant Architecture: A values-based moat.
    4. Superior Trader Psychology: Removes the "ticking clock" of funding rates.
    5. No Protocol vs. Trader Conflict: Interests are aligned with users.
    6. Radical Simplicity in Risk Management: Predictable break-even calculations.

    THE CORE JUSTIFICATION (BREAK-EVEN ANALYSIS):
    - Assumptions: Eswap (1% total fee) vs. Competitor (0.1% trade fee + 0.03% daily funding rate).
    - The Inflection Point: At approximately Day 30, Eswap becomes the cheaper option.
    - Holding Period Cost Comparison on a $10k position:
    - 30 Days: Eswap ($100), Competitor ($100).
    - 90 Days: Eswap ($100), Competitor ($280). You Save $180.
    - 180 Days: Eswap ($100), Competitor ($550). You Save $550.

    STRATEGIC POSITIONING:
    - Positioning Statement: "Eswap is the only decentralized exchange built for the high-conviction investor. We replace unpredictable, daily interest fees with a single, transparent 1% transaction fee, making us the most cost-effective platform for holding leveraged positions long-term. Trade your thesis, not the clock."
    """

    MARKETING_STRATEGY_CONTEXT = """
    DOCUMENT: Eswap Marketing Strategy Plan

    EXECUTIVE SUMMARY:
    This strategy targets the intersection of the $4-5 trillion Islamic finance market and the ~$152-160B TVL DeFi sector. It focuses on education-driven marketing to reframe the fee as a "Total Cost of Holding" advantage.
    - Goal: 25,000 users in Year 1 (2026).
    - Budget: $250K-$0.5M in Year 1.
    - Expected ROI: Drive $50M cumulative volume, break-even in 18 months.

    TARGET AUDIENCE:
    - Primary (60%): Pious Retail Investors in MENA ( UAE, Turkey) and Southeast Asia (Indonesia).
    - Secondary (30%): Long-Term Secular Investors globally, frustrated by funding rates.
    - Tertiary (10%): Strategic Hedgers & Institutions.

    POSITIONING AND MESSAGING:
    - Core Positioning: "The End of Funding Fees."
    - For Halal Users: "Unlock DeFi leverage without compromising your faith—100% Shariah-compliant, no riba, automatic haram filtering."
    - For Secular Users: "Fixed fee beats variable funding rates after ~15-30 days—predictable costs for high-conviction holds."

    CHANNELS AND TACTICS:
    - Social Media (30% budget): Daily posts, AMAs, polls on X/Twitter, Telegram, Discord.
    - Content Marketing (25% budget): Blog/academy with articles on "Hidden Funding Fees"; SEO for "Ethical crypto trading".
    - Influencer Partnerships (20% budget): Collaborate with 10 influencers (Islamic-focused and long-term analysts).
    - PR & Events (15% budget): Features in Islamic Finance News, attend fintech conferences.

    PLATFORMS & TOOLS:
    - Quest Platforms for community engagement: Galxe, QuestN, Zealy, TaskOn, Layer3.
    - Analytics Platforms for research (similar to DeFiLlama): De.Fi, Dune Analytics, Nansen, Messari.
    """

    USER_ACQUISITION_WALLET_PLAN_CONTEXT = """
    DOCUMENT: Distribution & User Acquisition Plan (Leveraging Wallets)

    EXECUTIVE SUMMARY:
    This strategy centers on leveraging wallet platforms to onboard users seamlessly. By integrating with high-user-base wallets, Eswap addresses accessibility challenges in the Halal DeFi landscape.
    - Goal: 25,000 users in Year 1.
    - Budget: $200K-$400K.
    - Expected: Drive $100M volume, 40% MoM growth.

    OBJECTIVES (POST Q1 2026 LAUNCH):
    - Wallet Integrations: Secure 5+ integrations (MetaMask Snaps, Trust Wallet, etc.) to reach 10M potential users by Q2 2026.
    - User Onboarding: Acquire 25K users with 40% MoM growth in the first 12 months.
    - Conversion: Achieve 5% conversion from wallet exposures to active traders.

    TARGET WALLETS & RATIONALE:
    - MetaMask (30M+ active): Supports ethical chains like HAQQ.
    - Trust Wallet (60M+ downloads): Multi-chain, aligns with Halal staking trends.
    - Coin98 (5M+): Multi-chain DeFi focus.
    - TokenPocket (30M+): Used for Halal payments.
    - Ledger (6M+ devices): Appeals to institutions, focuses on self-custody.
    - Narval (Institutional focus): Targets Islamic institutions with riba-free treasury.

    ACQUISITION TACTICS:
    - In-Wallet Promotions (e.g., Trust Wallet banners), Referral Programs ($ESW rewards), Educational Content (Webinars on "Halal Leverage via MetaMask"), and Cross-Promotions with Halal wallets.
    """
    DOCUMENTS = {
        "1": ("PITCH_DECK_SUMMARY", PITCH_DECK_CONTEXT),
        "2": ("BUSINESS_MODEL_CANVAS", BUSINESS_MODEL_CANVAS_CONTEXT),
        "3": ("COMPETITIVE_LANDSCAPE", COMPETITIVE_LANDSCAPE_CONTEXT),
        "4": ("INVESTMENT_THESIS", INVESTMENT_THESIS_CONTEXT),
        "5": ("MARKETING_STRATEGY", MARKETING_STRATEGY_CONTEXT),
        "6": ("USER_ACQUISITION_WALLET_PLAN", USER_ACQUISITION_WALLET_PLAN_CONTEXT),
    }

    DOCUMENT_DESCRIPTIONS = {
        "1": "Investor pitch deck summary: Covers the core problem (Riba), solution, traction ($250k raised), team bios, roadmap, and funding needs ($1.5M seed).",
        "2": "Business Model Canvas: Details key partners (0x, Uniswap), activities, resources, value proposition, customer segments, and revenue streams (1% fee).",
        "3": "Competitive Landscape Analysis: Analyzes competitors like MRHB DeFi and Haqq Network, and identifies strategic gaps in the Halal DEX market (Liquidity, Technology, Trust).",
        "4": "Investment Thesis: Explains the core financial argument, the 'Total Cost of Holding' concept, and the break-even analysis of the 1% fee vs. competitors.",
        "5": "Marketing Strategy: Outlines the go-to-market plan, target audience (Pious Retail, Secular Investors), messaging, budget, KPIs, and platforms to be used (Zealy, Galxe).",
        "6": "User Acquisition Plan via Wallets: A specific plan focusing on integrating with and marketing through crypto wallets like MetaMask and Trust Wallet to drive user growth.",
    }

# --- The Metrics Vault ---
METRICS = {
"funding_raised_usd": 250000,
"seed_round_target_usd": 1500000,
"grant_strategy_target_usd": 750000,
"user_target_y1": 25000,
"user_target_y3": 1000000,
"market_size_islamic_finance_trillion": 4.5,
"revenue_projection_y3_million": 52,
"team_size": 3,
"mvp_status": "Live on testnet",
"mainnet_launch_target": "Q1 2026",
"transaction_fee_percent": 1
}

# --- CORE API COMMUNICATION ---

def make_api_call(payload, system_prompt_text, retries=3):
    """
    Makes a single API call to Gemini with retry logic and rate limit handling.
    """
    model = genai.GenerativeModel(
        'gemini-1.5-flash',
        system_instruction=system_prompt_text
    )

    for attempt in range(retries):
        try:
            time.sleep(4)

            response = model.generate_content(payload['contents'])
            return response.text

        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                wait_time = 60 + random.uniform(1, 5)
                print(f"\n[Warning] Rate limit hit. Waiting {wait_time:.2f} seconds for quota to reset...")
                time.sleep(wait_time)
            else:
                return f"An error occurred: {e}"

    return "Error: Failed after max retries due to rate limits."


# --- THE "RED TEAM" AI CHAIN ---

def searcher_ai(user_query, grant_context, all_questions):
    """Step 0: The "Searcher" AI."""
    system_prompt = (
        "You are an expert researcher. Your goal is to find relevant information "
        "to help answer the user's query. You will be given a user query, the "
        "context of a grant application, and the full list of questions. Your task "
        "is to perform a web search and return a summary of the most relevant findings."
    )

    search_query = f"{user_query} {grant_context} {all_questions}"

    print(f"\n... [Searcher AI] Searching the web for: '{search_query}' ...")
    try:
        search_results = search(search_query, num_results=5)
        formatted_results = "\n".join([f"- {result}" for result in search_results])
        summary_prompt = (
            f"Please summarize the following search results in the context of the user's query:\n"
            f"User Query: {user_query}\n"
            f"Grant Context: {grant_context}\n"
            f"Search Results:\n{formatted_results}"
        )
        payload = {"contents": [{"parts": [{"text": summary_prompt}]}]}
        response_text = make_api_call(payload, system_prompt)
        return response_text

    except Exception as e:
        return f"An error occurred during the web search: {e}"

def select_best_documents(user_query, document_descriptions, searcher_results):
    """Step 1: The "Librarian" AI."""
    system_prompt = (
        "You are an intelligent document routing assistant. Analyze a user's question, "
        "external search results, and available internal documents to select the MOST "
        "relevant internal documents to answer the question. Only select documents "
        "that are absolutely necessary. Respond ONLY with a comma-separated list of "
        "document numbers. Example: 1, 4"
    )
    descriptions_text = "\n".join([f"{num}: {desc}" for num, desc in document_descriptions.items()])
    full_prompt = (
        f"--- EXTERNAL SEARCH RESULTS ---\n{searcher_results}\n\n"
        f"--- USER QUESTION ---\n'{user_query}'\n\n"
        f"--- AVAILABLE INTERNAL DOCUMENTS ---\n{descriptions_text}\n\n"
        "Based on the user question AND the external search results, which "
        "internal document numbers are most relevant to constructing the best answer? "
        "Return only the numbers, separated by commas."
    )
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    print("\n... [Librarian AI] Selecting best internal documents ...")
    response_text = make_api_call(payload, system_prompt)
    selected_ids = re.findall(r'\d+', response_text)

    valid_ids = [s_id for s_id in selected_ids if s_id in DOCUMENTS]

    if not valid_ids:
        print(f"[Warning] Librarian AI returned invalid or no document IDs ('{response_text}'). Using all documents as fallback.")
        return list(DOCUMENTS.keys())

    return valid_ids

def generate_final_answer(user_query, document_context, grant_context, persona, metrics, searcher_results):
    """Generates the final answer in a single step."""
    system_prompt = (
        "You are a world-class AI writer and grant reviewer, capable of producing a polished, final-version answer in a single step. "
        "Your process is to: "
        "1.  **Synthesize**: Internally combine the user's query, persona, application context, internal knowledge, external search results, and key metrics. "
        "2.  **Critique**: Mentally identify potential weaknesses, weak language, or missed opportunities in a hypothetical first draft. "
        "3.  **Refine**: Seamlessly incorporate feedback and insights from your internal critique into the final output. "
        "Your final answer MUST be perfectly aligned with the provided persona and context, well-supported by the knowledge base, and factually accurate according to the metrics. "
        "Provide only the final, polished text."
    )
    full_prompt = (
        f"--- ADOPT THIS PERSONA ---\n{persona}\n\n"
        f"--- APPLICATION CONTEXT (Your Primary Focus) ---\n{grant_context}\n\n"
        f"--- EXTERNAL SEARCH RESULTS (Use for additional context) ---\n{searcher_results}\n\n"
        f"--- METRICS DATA (Use for all numbers) ---\n{json.dumps(metrics, indent=2)}\n\n"
        f"--- INTERNAL KNOWLEDGE BASE (Use for all qualitative info) ---\n{document_context}\n\n"
        f"--- QUESTION TO ANSWER ---\n"
        f"Based on all the above, generate the single best, final-version answer to the following question:\n"
        f"'{user_query}'"
    )
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    print("... [Writer AI] Generating final answer ...")
    return make_api_call(payload, system_prompt)

# --- MAIN APPLICATION ORCHESTRATOR ---

def main():
    """Main function to run the strategic writing assistant application."""
    parser = argparse.ArgumentParser(description="Strategic Writing Assistant")
    parser.add_argument("--documents-dir", help="Path to the directory containing your documents (PDF, TXT, PPTX).")
    parser.add_argument("--non-interactive", action="store_true", help="Run in non-interactive mode for testing.")
    args = parser.parse_args()

    if not API_KEY:
        print("\n" + "!"*70 + "\n!!! FATAL ERROR: GEMINI_API_KEY environment variable is not set. !!!\n" + "!"*70)
        return

    if args.documents_dir:
        print(f"\n[Info] Loading documents from: {args.documents_dir}")
        load_documents_from_directory(args.documents_dir)
    else:
        print("\n[Info] No documents directory provided. Using hardcoded knowledge base.")
        load_hardcoded_documents()

    if not DOCUMENTS:
        print("\n[Error] No documents loaded. Please provide a valid documents directory or check the hardcoded content.")
        return

    print("\n" + "="*50)
    print(" Strategic Writing Assistant for Eswap ")
    print("="*50)

    if args.non_interactive:
        grant_context = "A general inquiry; no specific context provided."
        persona = "A professional and clear project representative."
        questions = ["What is this about?"]
    else:
        print("\n--- 1. Application Context Setup ---")
        print("Paste the grant/accelerator description, focus areas, or mission below.")
        print("Press Enter on an empty line when finished.")
        lines = []
        while True:
            try:
                line = input()
                if not line: break
                lines.append(line)
            except EOFError: break
        grant_context = "\n".join(lines)
        if not grant_context.strip():
            grant_context = "A general inquiry; no specific context provided."
            print("\n[Info] No context provided. Running in general Q&A mode.")
        else:
            print("\n[Success] Application context loaded.")

        print("\n--- 2. Persona & Tone Setup ---")
        print('Describe the ideal tone for this application. (Examples below)')
        print(' - "Ambitious, data-driven founder for a top-tier VC"')
        print(' - "Community-focused, humble builder for a DAO grant"')
        print(' - "Deeply technical, formal researcher for a foundation grant"')
        persona = input("[Ideal Tone]: ")
        if not persona.strip():
            persona = "A professional and clear project representative."
            print("\n[Info] Using default professional tone.")
        else:
            print("\n[Success] Persona and tone set.")

        print("\n" + "="*50)
        print(" Assistant Ready. Let's begin the application. ")
        print("="*50)
        print("Paste all your application questions below, one question per line.")
        print("Press Enter on an empty line when finished.")

        questions = []
        while True:
            try:
                line = input()
                if not line: break
                questions.append(line)
            except EOFError: break

    if not questions:
        print("\nNo questions provided. Exiting.")
        return

    sharia_keywords = ["sharia", "halal", "islamic", "riba", "muslim"]

    for i, user_question in enumerate(questions):
        print("\n" + "="*20 + f" PROCESSING QUESTION {i+1}/{len(questions)} " + "="*20)
        print(f"QUESTION: {user_question}")

        adapted_persona = persona
        if any(keyword in user_question.lower() for keyword in sharia_keywords):
            adapted_persona += (
                "\n\n--- SPECIAL INSTRUCTION ---\n"
                "The user's question is about Sharia/Islamic finance. "
                "You MUST prioritize and use terms like 'Sharia-compliant', 'halal', and 'riba-free' when describing the project's core value. "
                "This is the primary lens for the answer."
            )
        else:
            adapted_persona += (
                "\n\n--- SPECIAL INSTRUCTION ---\n"
                "The user's question is NOT explicitly about Sharia/Islamic finance. "
                "You MUST describe the project's value using secular terms like 'ethical finance', '0% interest', and 'fixed-fee model'. "
                "Avoid mentioning Sharia, halal, or Islamic finance unless it is directly quoted from the source documents provided."
            )

        searcher_results = searcher_ai(user_question, grant_context, questions)
        print("---------------------------")

        selected_doc_ids = select_best_documents(user_question, DOCUMENT_DESCRIPTIONS, searcher_results)

        combined_context = ""
        selected_names = []
        for doc_id in selected_doc_ids:
            if doc_id in DOCUMENTS:
                doc_name, doc_content = DOCUMENTS[doc_id]
                selected_names.append(doc_name)
                combined_context += f"\n--- DOC: {doc_name} ---\n{doc_content}\n"

        if not combined_context:
            print("[Error] Could not build context. Please try again.")
            continue
        print(f"[Info] Using knowledge from: {', '.join(selected_names)}")

        final_answer = generate_final_answer(user_question, combined_context, grant_context, adapted_persona, METRICS, searcher_results)
        print("\n" + "="*20 + " FINAL RECOMMENDED ANSWER " + "="*20)
        print(final_answer)
        print("="*66)

if __name__ == "__main__":
    main()
