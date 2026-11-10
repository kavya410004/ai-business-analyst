import asyncio

import streamlit as st

from src.agent.orchestrator import AgentOrchestrator

import traceback


# --------------------------------------------------
# Page configuration
# --------------------------------------------------

st.set_page_config(
    page_title="AI Business Analyst",
    page_icon="📊",
    layout="wide",
)

st.title("📊 AI Business Analyst")
st.caption(
    "Ask questions about revenue, sales performance, "
    "pipeline health and collections."
)


# --------------------------------------------------
# Session state
# --------------------------------------------------

if "agent" not in st.session_state:
    st.session_state.agent = AgentOrchestrator()

if "messages" not in st.session_state:
    st.session_state.messages = []


# --------------------------------------------------
# Sidebar
# --------------------------------------------------

with st.sidebar:
    st.header("About")
    st.write(
        "An AI-powered business analyst that answers "
        "questions using company data and analytics tools."
    )

    st.divider()

    st.subheader("Example questions")

    st.markdown("""
    - How are we doing in Q3 2026?
    - Compare revenue in Q3 and Q2 2026.
    - Which region has the lowest win rate?
    - Why did win rate change in Q3?
    - Which segment pays the slowest?
    - What are our outstanding receivables?
    """)

    st.divider()

    if st.button("Clear conversation", use_container_width=True):
        st.session_state.agent.reset_conversation()
        st.session_state.messages = []
        st.rerun()


# --------------------------------------------------
# Display conversation history
# --------------------------------------------------

for message in st.session_state.messages:

    with st.chat_message(message["role"]):

        st.markdown(message["content"])

        if message["role"] == "assistant":

            if message.get("model_used"):
                st.caption(f"Model: {message['model_used']}")

            executions = message.get("tool_executions", [])

            if executions:
                with st.expander(
                    f"View execution details ({len(executions)} tool calls)",
                    expanded=False
                ):
                    for index, execution in enumerate(executions, 1):

                        st.markdown(
                            f"**{index}. {execution['name']}**"
                        )

                        st.caption("Arguments")
                        st.json(execution["arguments"])

                        st.caption("Tool result")
                        st.json(execution["result"])

                        if index < len(executions):
                            st.divider()


# --------------------------------------------------
# Chat input
# --------------------------------------------------

question = st.chat_input("Ask a business question...")

if question:

    # Display user message
    st.session_state.messages.append({
        "role": "user",
        "content": question,
    })

    with st.chat_message("user"):
        st.markdown(question)

    # Generate agent response
    with st.chat_message("assistant"):

        with st.spinner("Analyzing your business data..."):

            try:
                response = asyncio.run(
                    st.session_state.agent.ask(question)
                )

                st.markdown(response.answer)

                if response.model_used:
                    st.caption(f"Model: {response.model_used}")

                executions = [
                    {
                        "name": execution.name,
                        "arguments": execution.arguments,
                        "result": execution.result,
                    }
                    for execution in response.tool_executions
                ]

                if executions:
                    with st.expander(
                        f"View execution details ({len(executions)} tool calls)",
                        expanded=False
                    ):
                        for index, execution in enumerate(executions, 1):

                            st.markdown(
                                f"**{index}. {execution['name']}**"
                            )

                            st.caption("Arguments")
                            st.json(execution["arguments"])

                            st.caption("Tool result")
                            st.json(execution["result"])

                            if index < len(executions):
                                st.divider()

                # Save assistant response
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response.answer,
                    "tool_executions": executions,
                    "model_used": response.model_used,
                })

            except Exception:
                st.error("Something went wrong while processing your question.")

                st.code(
                    traceback.format_exc(),
                    language="python",
                )