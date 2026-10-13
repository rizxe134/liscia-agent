"""python agent.py            -> chat app
python agent.py "task"     -> run one task in the console"""
import argparse, os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from core import Agent, load_config

def main():
    p = argparse.ArgumentParser(description="Local computer-use agent (Ollama)")
    p.add_argument("task", nargs="?", help="task to run in console mode (omit to open the chat app)")
    p.add_argument("--model"); p.add_argument("--max-steps", type=int)
    p.add_argument("--config", default="config.yaml"); p.add_argument("--ui", action="store_true")
    a = p.parse_args(); cfg = load_config(a.config)
    if a.model: cfg["ollama"]["model"] = a.model
    if a.max_steps: cfg["agent"]["max_steps"] = a.max_steps
    if a.ui or not a.task:
        import ui; ui.launch(cfg); return
    agent = Agent(cfg)
    models = agent.client.check()
    if models is None: sys.exit("Ollama is not running. Start the Ollama app (or `ollama serve`).")
    if not any(m.startswith(cfg["ollama"]["model"]) for m in models):
        print(f"Warning: model {cfg['ollama']['model']} not pulled. Run: ollama pull {cfg['ollama']['model']}")
    print("Starting in 3s - switch to the window you want it to use..."); import time; time.sleep(3)
    agent.run(a.task)

if __name__ == "__main__":
    main()
