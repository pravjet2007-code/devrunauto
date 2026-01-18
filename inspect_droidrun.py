import inspect
from dataclasses import fields
from droidrun.config_manager import DroidrunConfig, AgentConfig

print("\nAgentConfig fields:")
try:
    for f in fields(AgentConfig):
        print(f"- {f.name}: {f.type}")
except Exception as e:
    print(f"Error inspecting AgentConfig: {e}")
