import typer
from rich import print

app = typer.Typer(help="Local LLM Wiki with Obsidian support")

@app.command()
def init(name: str = typer.Argument("my-wiki")):
    print(f"✅ Initialized Obsidian-ready vault: {name}/")
    # TODO: create folders

@app.command()
def ingest(path: str):
    print(f"🚀 Ingesting {path}...")

if __name__ == "__main__":
    app()