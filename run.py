"""Entry point: python run.py"""
import uvicorn

from app import config

if __name__ == "__main__":
    print(f"\n  Gujarat News Intelligence")
    print(f"  Dashboard: http://{config.HOST}:{config.PORT}")
    llm = f"ON ({config.LLM_PROVIDER}: {config.LLM_MODEL})" if config.LLM_ENABLED \
        else "OFF - heuristic fallback (set ANTHROPIC_API_KEY or GROQ_API_KEY in .env)"
    print(f"  LLM analysis: {llm}\n")
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT)
