import asyncio

from src.agent.orchestrator import AgentOrchestrator


async def main():
    agent = AgentOrchestrator()

    question = "How are we doing in Q3 2026?"

    print(f"\nQuestion: {question}\n")

    response = await agent.ask(question)

    print("=" * 60)
    print("AGENT ANSWER")
    print("=" * 60)
    print(response.answer)

    print("\n" + "=" * 60)
    print("TOOL EXECUTION TRACE")
    print("=" * 60)

    for execution in response.tool_executions:
        print(f"\nTool: {execution.name}")
        print(f"Arguments: {execution.arguments}")
        print(f"Result: {execution.result}")

    print(f"\nModel used: {response.model_used}")


if __name__ == "__main__":
    asyncio.run(main())