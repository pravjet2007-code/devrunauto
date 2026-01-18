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
    from droidrun.agent.utils.llm_picker import load_llm
    from droidrun.config_manager import DroidrunConfig, AgentConfig, ManagerConfig, ExecutorConfig, TelemetryConfig
except ImportError:
    print("CRITICAL ERROR: 'droidrun' library not found or incompatible version.")
    print("Please ensure you have installed it: pip install droidrun")
    sys.exit(1)

load_dotenv()

class PharmacyAgent:
    """
    Agent to compare medicine prices across PharmEasy, Apollo 24|7, and Tata 1mg.
    Follows the Professional Architecture.
    """
    
    def __init__(self, provider="gemini", model="models/gemini-2.5-flash"):
        self.provider = provider
        self.model = model
        self._ensure_api_keys()

    def _ensure_api_keys(self):
        if self.provider == "gemini" and not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
             print("[Warn] GEMINI_API_KEY not found in env, checking GOOGLE_API_KEY")

    def _parse_price(self, price_str):
        if not price_str: return float('inf')
        try:
            clean = str(price_str).lower().replace(',', '').replace('₹', '').replace('rs', '').replace('rs.', '').strip()
            match = re.search(r'\d+(\.\d+)?', clean)
            return float(match.group()) if match else float('inf')
        except:
            return float('inf')

    async def execute_task(self, app_name: str, medicine: str, role: str) -> dict:
        print(f"\n[PharmaAgent] Initializing Task for: {app_name} ({role} mode)")
        
        # Mode-specific instructions
        if role == "pharmacist":
            search_instruction = (
                f"Search for '{medicine}'. "
                f"Look specifically for 'bulk packs', 'combo packs', 'wholesale', or largest available strip sizes suitable for restocking. "
                f"If bulk options aren't explicitly labeled, find the standard pack with the best value."
            )
            report_instruction = "Report the Price, Quantity/Pack Size, and calculated Unit Price if possible."
        else:
            search_instruction = f"Search for '{medicine}'. Identify the exact medicine matching the name and dosage."
            report_instruction = "Report the Price and Pack Size."

        goal = (
            f"Open the app '{app_name}'. "
            f"If a 'Location Permission' popup appears, click 'While using the app' or 'Allow'. "
            f"Click on the search bar. "
            f"{search_instruction} "
            f"Visually identify the best result. "
            f"Read the price and details. "
            f"{report_instruction} "
            f"Return a strict JSON object with keys: 'app', 'medicine', 'price', 'details'. "
            f"Ensure strict JSON format."
        )

        # --- Professional Config Setup ---
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        provider_name = "GoogleGenAI" if self.provider == "gemini" else self.provider

        llm = load_llm(
            provider_name=provider_name,
            model=self.model,
            api_key=api_key
        )

        manager_config = ManagerConfig(vision=True)
        executor_config = ExecutorConfig(vision=True)
        agent_config = AgentConfig(
            reasoning=True,
            manager=manager_config,
            executor=executor_config
        )
        telemetry_config = TelemetryConfig(enabled=False)
        config = DroidrunConfig(
            agent=agent_config,
            telemetry=telemetry_config
        )

        agent = DroidAgent(
            goal=goal,
            llms=llm,
            config=config
        )

        result_data = {"app": app_name, "status": "failed", "data": {}, "numeric_price": float('inf')}

        try:
            print(f"[PharmaAgent] 🧠 Running Agent on {app_name}...")
            result = await agent.run()
            
            # --- Robust Output Parsing ---
            if result:
                if hasattr(result, 'reason'):
                     clean_json = str(result.reason).strip()
                else:
                     clean_json = str(result).strip()

                if "<request_accomplished" in clean_json:
                    try:
                        clean_json = clean_json.split(">")[1].split("</request_accomplished>")[0].strip()
                    except IndexError:
                        pass

                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                
                if clean_json.startswith("{"):
                    try:
                        data = json.loads(clean_json)
                        result_data["data"] = data
                        result_data["status"] = "success"
                        result_data["numeric_price"] = self._parse_price(data.get("price"))
                    except json.JSONDecodeError:
                        print(f"[Warn] JSON Decode Error: {clean_json}")
                else:
                     print(f"[Warn] Agent output was not JSON: {clean_json[:50]}...")
            
            return result_data

        except Exception as e:
            print(f"[Error] Task Execution Failed for {app_name}: {e}")
            return result_data

    async def compare_prices(self, medicine, role):
        apps = ["PharmEasy", "Apollo 24|7", "Tata 1mg"]
        results = {}

        for app in apps:
            res = await self.execute_task(app, medicine, role)
            results[app] = res
            await asyncio.sleep(2) 

        print(f"\n--- Final Aggregated Results for '{medicine}' ({role}) ---")
        best_option = None
        min_price = float('inf')

        for app, res in results.items():
            if res["status"] == "success":
                price = res["numeric_price"]
                details = res["data"].get("details", "")
                print(f"{app}: {res['data'].get('price')} - {details}")
                
                if price < min_price:
                    min_price = price
                    best_option = res
            else:
                print(f"{app}: Failed to get data.")

        results["best_option"] = best_option

        if best_option:
            print(f"\n🏆 Best Option: {best_option['app']} - {best_option['data'].get('price')}")
        else:
            print("\n❌ Could not determine best option.")
        
        return results

async def main():
    parser = argparse.ArgumentParser(description="Pharmacy Agent (Patient/Pharmacist)")
    parser.add_argument("--medicine", required=True, help="Name of the medicine")
    parser.add_argument("--role", choices=['patient', 'pharmacist'], default='patient', help="User role")
    args = parser.parse_args()

    agent = PharmacyAgent(model="models/gemini-2.5-flash")
    await agent.compare_prices(args.medicine, args.role)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
