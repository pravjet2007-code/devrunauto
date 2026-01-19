import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import Agents
from commerce_agent import CommerceAgent
from ride_comparison_agent import RideComparisonAgent
from pharmacy_agent import PharmacyAgent
from event_coordinator_agent import EventCoordinatorAgent

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DroidServer")

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- InMemory Task Store ---
# Structure: { task_id: { "id": str, "persona": str, "status": str, "logs": list, "result": Any, "timestamp": str } }
task_history: List[Dict[str, Any]] = []

def add_task_record(task_id: str, persona: str, payload: Any):
    record = {
        "id": task_id,
        "persona": persona,
        "status": "running",
        "created_at": datetime.now().isoformat(),
        "logs": [],
        "result": None,
        "payload": payload.dict()
    }
    task_history.insert(0, record) # Newest first
    return record

def update_task_status(task_id: str, status: str, result: Any = None):
    for task in task_history:
        if task["id"] == task_id:
            task["status"] = status
            if result:
                task["result"] = result
            break

def append_task_log(task_id: str, message: str):
    for task in task_history:
        if task["id"] == task_id:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] {message}"
            task["logs"].append(log_entry)
            break

# WebSocket Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        # Legacy support if needed, but we prefer structured
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

    async def broadcast_json(self, data: Dict[str, Any]):
        message = json.dumps(data, default=str)
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()

# Data Models
class TaskPayload(BaseModel):
    persona: str
    product: str = None
    pickup: str = None
    drop: str = None
    medicine: str = None
    # For Foodie
    food_item: str = None
    action: str = "search" # 'search' or 'order'
    # For Coordinator
    event_name: str = None
    guest_list: list = [] # [{'name':..., 'phone':...}]
    
@app.get("/")
async def root():
    return {"status": "DroidRun Server Running"}

@app.get("/tasks")
async def get_tasks():
    return task_history

@app.get("/tasks/{task_id}")
async def get_task_details(task_id: str):
    for task in task_history:
        if task["id"] == task_id:
            return task
    return {"error": "Task not found"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
            # Keep alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def log_and_broadcast(task_id: str, message: str):
    """Save log to history and broadcast to WS"""
    append_task_log(task_id, message)
    await manager.broadcast_json({
        "type": "log",
        "task_id": task_id,
        "message": message
    })

async def run_agent_task(payload: TaskPayload):
    """
    Executes the agent logic based on persona.
    Broadcasts logs to WebSocket.
    """
    task_id = str(uuid.uuid4())
    add_task_record(task_id, payload.persona, payload)
    
    # Notify start
    await manager.broadcast_json({
        "type": "start",
        "task_id": task_id,
        "persona": payload.persona,
        "timestamp": datetime.now().isoformat()
    })

    await log_and_broadcast(task_id, f"🚀 Starting Executor for Persona: {payload.persona}")
    
    result = None
    status = "failed"
    
    try:
        if payload.persona == "shopper":
            agent = CommerceAgent(model="models/gemini-2.5-flash")
            await log_and_broadcast(task_id, f"Searching for {payload.product} on Amazon/Flipkart...")
            
            result = await agent.execute_task("Amazon", payload.product, "product") 
            
            if result['status'] == 'failed':
                 await log_and_broadcast(task_id, "Amazon failed, trying Flipkart...")
                 result = await agent.execute_task("Flipkart", payload.product, "product")
                 
        elif payload.persona == "rider":
            agent = RideComparisonAgent(model="models/gemini-2.5-flash")
            await log_and_broadcast(task_id, f"Comparing rides from {payload.pickup} to {payload.drop}...")
            full_res = await agent.compare_rides(payload.pickup, payload.drop)
            result = full_res.get('best_deal', {"status": "failed"})
            
        elif payload.persona == "patient":
            agent = PharmacyAgent(model="models/gemini-2.5-flash")
            await log_and_broadcast(task_id, f"Searching for medicine: {payload.medicine}...")
            full_res = await agent.compare_prices(payload.medicine, "patient")
            result = full_res.get('best_option', {"status": "failed"})

        elif payload.persona == "foodie":
             agent = CommerceAgent(model="models/gemini-2.5-flash")
             await log_and_broadcast(task_id, f"🍔 Foodie Mode Activated: {payload.action.upper()} '{payload.food_item}'")
             
             if payload.action == 'order':
                 await log_and_broadcast(task_id, "Initiating autonomous order sequence...")
                 order_res = await agent.auto_order_cheapest(payload.food_item)

                 final_status = order_res.get('order_status', {}).get('status', 'unknown')
                 if final_status == 'success':
                     msg = "✅ Order Placed Successfully!"
                 else:
                     msg = "⚠️ Order Attempted (Check Device)."

                 result = {
                     "status": "success",
                     "message": msg,
                     "details": order_res
                 }

             else:
                 await log_and_broadcast(task_id, "Searching Zomato and Swiggy...")
                 results = {}
                 platforms = ["Zomato", "Swiggy"]
                 for p in platforms:
                      await log_and_broadcast(task_id, f"Checking {p}...")
                      res = await agent.execute_task(p, payload.food_item, "food item", action="search")
                      results[p.lower()] = res
                      await asyncio.sleep(1)
                 
                 z_price = results.get('zomato', {}).get('data', {}).get('price', 'N/A')
                 s_price = results.get('swiggy', {}).get('data', {}).get('price', 'N/A')
                 
                 zp = float(results.get('zomato', {}).get('data', {}).get('numeric_price', float('inf')))
                 sp = float(results.get('swiggy', {}).get('data', {}).get('numeric_price', float('inf')))
                 
                 winner = "None"
                 if zp < sp: winner = "Zomato"
                 elif sp < zp: winner = "Swiggy"
                 elif zp == sp and zp != float('inf'): winner = "Tie"

                 await log_and_broadcast(task_id, f"Prices found: Zomato ({z_price}), Swiggy ({s_price})")
                 result = {
                     "status": "success", 
                     "message": f"Best Deal Found: {winner}. (Zomato: {z_price}, Swiggy: {s_price})",
                     "details": results
                 }

        elif payload.persona == "coordinator":
            agent = EventCoordinatorAgent(model="models/gemini-2.5-flash")
            await log_and_broadcast(task_id, f"🎪 Orchestrating Event: {payload.event_name}")
            logistics = [] 
            await agent.orchestrate_event(payload.event_name, payload.guest_list, logistics)
            result = {"status": "success", "message": "Event Orchestration Complete"}

        # Determine final status
        if result:
            status = "success"
            await log_and_broadcast(task_id, f"✅ Task Complete.")
        else:
            status = "failed"
            await log_and_broadcast(task_id, "❌ Task Failed or Returned No Data.")

    except Exception as e:
        logger.error(f"Task Error: {e}")
        status = "failed"
        result = {"error": str(e)}
        await log_and_broadcast(task_id, f"🔥 Error: {str(e)}")

    # Update History and Broadcast Completion
    update_task_status(task_id, status, result)
    await manager.broadcast_json({
        "type": "complete",
        "task_id": task_id,
        "status": status,
        "result": result
    })

@app.post("/task")
async def create_task(payload: TaskPayload):
    # Run in background
    asyncio.create_task(run_agent_task(payload))
    return {"status": "accepted", "message": "Task queued"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
