import os
import json
import argparse
import asyncio
import re
from dotenv import load_dotenv

# Conforming to STRICT user documentation example
try:
    from droidrun import DroidAgent
    from droidrun.config_manager import DroidrunConfig
except ImportError:
    DroidAgent = None
    DroidrunConfig = None

# Load environment variables
load_dotenv()

def parse_price(price_str):
    """
    Robust parser for prices like '₹1,499', 'Rs. 500', '$20.00'
    """
    if not price_str: return float('inf')
    try:
        # 1. Lowercase and remove common currency text
        clean = str(price_str).lower().replace(',', '').replace('₹', '').replace('rs', '').replace('rs.', '').strip()
        # 2. Extract the first valid float number
        match = re.search(r'\d+(\.\d+)?', clean)
        return float(match.group()) if match else float('inf')
    except:
        return float('inf')

def parse_rating(rating_str):
    try:
        clean = str(rating_str).strip()
        match = re.search(r'\d+(\.\d+)?', clean)
        return float(match.group()) if match else 0.0
    except:
        return 0.0

async def perform_search(app_name, query, item_type="product"):
    """
    Executes a DroidAgent run for a specific app search.
    """
    if DroidAgent is None:
         raise ImportError("droidrun library not found. Please install it.")

    print(f"\n[Status] 🟡 Initializing Agent for {app_name}...")
    
    # OPTIMIZATION 1: Strengthen the prompt to ensure JSON purity
    # We instruct the agent to explicitly IGNORE sponsored results if possible.
    task_goal = (
        f"Step 1: Go to the device home screen to ensure a clean state. "
        f"Step 2: Open {app_name}. "
        f"Step 3: Search for '{query}'. "
        f"Step 4: Analyze the visual search results. Ignore 'Sponsored' items if possible. "
        f"Step 5: Extract the top 3 {item_type}s. "
        f"Step 6: Return a STRICT JSON list with keys: 'title' (string), 'price' (string), 'rating' (string). "
        f"Do not write any conversational text. Output ONLY the JSON string."
    )
    
    config = DroidrunConfig()
    
    # Initialize Agent
    agent = DroidAgent(
        goal=task_goal,
        config=config
    )
    
    print(f"[Run] 🚀 Executing Agent on {app_name}...")
    
    # Run Agent (Async)
    output = await agent.run()
    
    # Parse Result
    result_data = {
        "platform": app_name,
        "status": "failed",
        "items": [],
        "best_item": None,
        "raw_response": str(output)
    }
    
    try:
        # Parsing logic to handle potential Markdown wrapping by the LLM
        json_str = str(output).strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
             json_str = json_str.split("```")[1].split("```")[0].strip()
        
        # Validation heuristic
        if json_str.startswith('[') or json_str.startswith('{'):
             items = json.loads(json_str)
             if isinstance(items, dict): items = [items] # handle single item
             
             valid_items = []
             for item in items:
                item['numeric_price'] = parse_price(item.get('price', '999999'))
                item['numeric_rating'] = parse_rating(item.get('rating', '0'))
                
                # Filter out garbage parses (e.g. price was "See details")
                if item['numeric_price'] > 0 and item['numeric_price'] != float('inf'):
                    valid_items.append(item)
                    
             result_data["items"] = valid_items
             result_data["status"] = "success"
             
             if valid_items:
                 # Sort by Price (Low to High), then Rating (High to Low)
                 valid_items.sort(key=lambda x: (x['numeric_price'], -x['numeric_rating']))
                 result_data["best_item"] = valid_items[0]
                 
    except Exception as e:
        print(f"[{app_name}] ❌ Parsing Error: {e}")
        # Keep raw_response in result_data for debugging
        
    return result_data

async def main_async():
    parser = argparse.ArgumentParser(description="DroidRun Commerce Agent (Async)")
    parser.add_argument("--task", choices=['shopping', 'food'], default='shopping', help="Type of task")
    parser.add_argument("--query", required=True, help="Item to search for")
    
    args = parser.parse_args()
    
    platforms = []
    item_type = "product"
    if args.task == "shopping":
        platforms = ["Amazon", "Flipkart"]
        item_type = "product"
    elif args.task == "food":
        platforms = ["Zomato", "Swiggy"]
        item_type = "food"
        
    results = {}
    
    for i, plat in enumerate(platforms):
        # OPTIMIZATION 2: Clean slate delay
        if i > 0:
            print("[System] ⏳ Cooling down for 3 seconds before switching apps...")
            await asyncio.sleep(3)
            
        res = await perform_search(plat, args.query, item_type)
        results[plat.lower()] = res
        
        if res['status'] == 'failed':
            print(f"[Warning] Search failed for {plat}. Agent output: {res['raw_response'][:100]}...")

    # Comparison Logic
    param1 = results.get(platforms[0].lower(), {}).get('best_item')
    param2 = results.get(platforms[1].lower(), {}).get('best_item')
    
    best_platform = None
    recommendation = "No valid items found on either platform."
    
    # Safe comparison handling
    p1_price = param1['numeric_price'] if param1 else float('inf')
    p2_price = param2['numeric_price'] if param2 else float('inf')
    
    if p1_price == float('inf') and p2_price == float('inf'):
        pass # Keep default recommendation
    elif p1_price < p2_price:
        best_platform = platforms[0]
        diff = p2_price - p1_price if p2_price != float('inf') else 0
        recommendation = f"{platforms[0]} is cheaper by ₹{diff:.0f}."
    elif p2_price < p1_price:
        best_platform = platforms[1]
        diff = p1_price - p2_price if p1_price != float('inf') else 0
        recommendation = f"{platforms[1]} is cheaper by ₹{diff:.0f}."
    else:
         # Tie-breaker: Rating
         p1_rate = param1['numeric_rating'] if param1 else 0
         p2_rate = param2['numeric_rating'] if param2 else 0
         
         if p1_rate > p2_rate:
            best_platform = platforms[0]
            recommendation = f"Prices equal, but {platforms[0]} has better rating ({p1_rate} vs {p2_rate})."
         else:
            best_platform = platforms[1]
            recommendation = f"Prices equal, but {platforms[1]} has better rating ({p2_rate} vs {p1_rate})."

    final_output = {
        "query": args.query,
        "category": args.task,
        "winner_platform": best_platform,
        "recommendation": recommendation,
        "details": results
    }
    
    # Print FINAL valid JSON for the Frontend to consume
    print(json.dumps(final_output, indent=2))

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()