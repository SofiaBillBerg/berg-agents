"""Run agent on staged files for CI."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from berg_agents.agents.codeagent import build_agent, create_default_tools
from berg_agents.main import create_llm, load_config
from langchain.messages import AIMessage, HumanMessage

THREAD_ID = "ci-run"


def get_staged_files() -> list[str]:
    """Get list of staged files from git.

    :return: List of staged file paths
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", "--cached", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [f.strip() for f in result.stdout.split("\n") if f.strip()]


def main() -> None:
    """Run agent review on staged files.

    This script is intended to be run as part of a CI pipeline.
    It will review all staged files and save the review to .ci/llm_review.txt.
    """
    staged = get_staged_files()

    if not staged:
        print("No staged files to review.")
        sys.exit(0)

    print(f"Reviewing {len(staged)} staged files...")

    # Load config and create agent
    cfg = load_config()
    llm = create_llm(cfg)
    root_dir = Path(cfg.get("root_dir", ".")).resolve()
    tools = create_default_tools(root_dir=str(root_dir), llm=llm)
    agent = build_agent(llm=llm, tools=tools)

    # Create review prompt
    files_list = "\n".join(f"- {f}" for f in staged)
    prompt = f"""Review these staged files for potential issues:

{files_list}

Check for:
- Code quality issues
- Potential bugs
- Security concerns
- Best practice violations

Provide a comprehensive review."""

    # Run review
    response = agent.invoke(
        {"messages": [HumanMessage(content=prompt)]},
        config={
            "configurable": {"thread_id": THREAD_ID},
            "recursion_limit": 150,
        },
    )

    # Save review
    review_path = Path(".ci/llm_review.txt")
    review_path.parent.mkdir(exist_ok=True)

    ai_messages = [
        msg
        for msg in response.get("messages", [])
        if isinstance(msg, AIMessage)
    ]
    output = str(ai_messages[-1].content) if ai_messages else str(response)
    review_path.write_text(output, encoding="utf-8")

    print(f"Review saved to {review_path}")


if __name__ == "__main__":
    main()
