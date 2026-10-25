"""3.0.0: a tiny built-in MCP server for trying MCP without Node (run: `Liscia Agent --mcp-demo`, or python mcpdemo.py).
Read-only tools only."""
import datetime, os, platform

def main():
    try: from mcp.server.mcpserver import MCPServer as Server   # mcp 2.x
    except ImportError: from mcp.server.fastmcp import FastMCP as Server  # mcp 1.x
    from mcp.types import ToolAnnotations
    ro = ToolAnnotations(readOnlyHint=True)
    srv = Server("liscia-demo")

    @srv.tool(annotations=ro, description="Current date and time on this computer.")
    def now() -> str:
        return datetime.datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M %Z")

    @srv.tool(annotations=ro, description="List the files and folders in a folder (default: home folder).")
    def list_folder(path: str = "~") -> str:
        p = os.path.expanduser(path or "~")
        items = sorted(os.listdir(p))[:200]
        return f"{p} ({len(items)} items):\n" + "\n".join(("[dir] " if os.path.isdir(os.path.join(p, i)) else "") + i for i in items if not i.startswith("."))

    @srv.tool(annotations=ro, description="Basic facts about this computer (OS, Python, CPU count).")
    def system_info() -> str:
        return f"{platform.system()} {platform.release()} · {platform.machine()} · {os.cpu_count()} CPUs · Python {platform.python_version()}"

    @srv.tool(annotations=ro, description="Add two numbers.")
    def add(a: float, b: float) -> float:
        return a + b

    srv.run()

if __name__ == "__main__":
    main()
