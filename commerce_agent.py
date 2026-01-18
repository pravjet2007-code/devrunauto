import os
import json
import argparse
import asyncio
import re
import sys
from dotenv import load_dotenv

# --- DroidRun Professional Architecture Imports ---
try:
    from droidrun.agent.droid import DroidAgent
    from droidrun.config_manager import DroidrunConfig
except ImportError:
    print("CRITICAL ERROR: 'droidrun' library not found or incompatible version.")
    print("Please ensure you have installed it: pip install droidrun")
    sys.exit(1)

# Load environment variables
load_dotenv()

class CommerceAgent:
    """
    Professional Commerce Agent using DroidRun Framework.
    Follows the 'Brain' (Host) and 'Senses' (Portal) architecture.
    """
    
    def __init__(self, provider="gemini", model="gemini-1.5-flash"):
        self.provider = provider
        self.model = model
        self._ensure_api_keys()

    def _ensure_api_keys(self):
        if self.provider == "gemini" and not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
             # Fallback check
             print("[Warn] GEMINI_API_KEY not found in env, checking GOOGLE_API_KEY")

    def _parse_price(self, price_str):
        """Robust price parsing utility."""
        if not price_str: return float('inf')
        try:
            clean = str(price_str).lower().replace(',', '').replace('₹', '').replace('rs', '').replace('rs.', '').strip()
            match = re.search(r'\d+(\.\d+)?', clean)
            return float(match.group()) if match else float('inf')
        except:
            return float('inf')

    async def execute_task(self, app_name: str, query: str, item_type: str) -> dict:
        """
        Spawns a DroidAgent to execute a specific commerce task.
        Uses Vision capabilities for better UI understanding.
        """
        print(f"\n[CommerceAgent] Initializing Task for: {app_name}")
        
        # 1. Define Goal (Natural Language with Structural Constraints)
        goal = (
            f"Open the app '{app_name}'. "
            f"Search for '{query}'. "
            f"Visually identify the best search result for {item_type}. "
            f"Extract the Title, Price, and Rating. "
            f"Return a JSON object with keys: 'title', 'price', 'rating'. "
            f"Ensure strict JSON format."
        )

        # 2. Configure Agent (Professional Pattern)
        # Using Vision for robustness against custom UI (Flutter/React Native)
        # 2. Configure Agent (Professional Pattern)
        # Using load_llm to avoid DroidrunConfig error
        from droidrun.agent.utils.llm_picker import load_llm
        from droidrun.config_manager import DroidrunConfig, AgentConfig, ManagerConfig, ExecutorConfig
        
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        llm = load_llm(
            provider_name="GoogleGenAI",
            model=self.model,
            api_key=api_key
        )

        # Create properly typed config
        # Enable vision for Manager (planning) and Executor (acting)
        manager_config = ManagerConfig(vision=True)
        executor_config = ExecutorConfig(vision=True)
        
        agent_config = AgentConfig(
            reasoning=True,
            manager=manager_config,
            executor=executor_config
        )
        
        config = DroidrunConfig(agent=agent_config)

        agent = DroidAgent(
            goal=goal,
            llms=llm,          # Correct argument name is 'llms'
            config=config,     # Pass the structured config
            # use_vision=True, # REMOVED: Managed via config
            # reasoning=True,  # REMOVED: Managed via config
            # temperature=0.0  # REMOVED: Not accepted by Workflow base class directly? 
            # If temperature controls LLM, it should be in LLM object or config. 
            # llm object already has temperature if set during load_llm, but load_llm doesn't seem to take temp.
            # We trust defaults/LLM profile for now.
        )

        # 3. Execute
        start_data = {"platform": app_name, "status": "failed", "data": {}}
        try:
            print(f"[CommerceAgent] 🧠 Running Agent Logic...")
            result = await agent.run()
            
            # 4. Parse Output
            if result:
                clean_json = str(result).strip()
                
                # XML tag cleanup (common with DroidRun Reasoning)
                if "<request_accomplished" in clean_json:
                    try:
                        clean_json = clean_json.split(">")[1].split("</request_accomplished>")[0].strip()
                    except IndexError:
                        pass
                
                # Markdown cleanup
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                
                # Heuristic validation
                if clean_json.startswith("{"):
                    start_data["data"] = json.loads(clean_json)
                    start_data["status"] = "success"
                    # Add numeric price for comparison logic
                    start_data["data"]["numeric_price"] = self._parse_price(start_data["data"].get("price"))
                else:
                     print(f"[Warn] Agent output was not JSON: {clean_json[:50]}...")
            else:
                 print("[Warn] Agent returned None result.")
            
            return start_data

        except Exception as e:
            print(f"[Error] Task Execution Failed: {e}")
            return start_data

async def main():
    parser = argparse.ArgumentParser(description="BestBuy-Agent: Commerce Automation (DroidRun)")
    parser.add_argument("--task", choices=['shopping', 'food'], default='shopping')
    parser.add_argument("--query", required=True)
    args = parser.parse_args()

    # Domain Configuration
    if args.task == "shopping":
        platforms = ["Amazon", "Flipkart"]
        item_type = "product"
    else:
        platforms = ["Zomato", "Swiggy"]
        item_type = "food item"

    # Initialize Controller
    # Using 2.5 Flash as recommended by quotas
    commerce_bot = CommerceAgent(provider="gemini", model="models/gemini-2.5-flash")
    
    results = {}

    # Sequential Execution (Single Device limitation)
    for platform in platforms:
        res = await commerce_bot.execute_task(platform, args.query, item_type)
        results[platform.lower()] = res
        # Brief cooldown for app switching stability
        await asyncio.sleep(2)

    # Output (Stdout for Backend Integration)
    print("\n--- Final Aggregated Results ---")
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())