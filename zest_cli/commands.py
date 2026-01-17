"""
Command generation, validation, and user interaction for Zest CLI.
"""

import re
import platform

from config import AFFIRMATIVE, NEGATIVE


def get_os_type() -> str:
    """Get the operating system type for the system prompt."""
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    elif system == "Linux":
        return "Linux"
    elif system == "Windows":
        return "Windows"
    return "Unix"


def check_query_quality(query: str) -> tuple[bool, int, bool, bool]:
    """
    Check if query is too long, vague, or likely shell-mangled.
    Returns (is_good, word_count, has_vague_language, likely_shell_mangled).
    """
    word_count = len(query.split())
    likely_shell_mangled = word_count > 100

    vague_indicators = [
        "help me", "urgent", "trouble", "problem",
        "boss", "deadline", "asap",
        "something like", "or something", "i think", "maybe", "probably",
        "i cant seem", "would you be able", "could you",
        "can you help", "im not sure", "i dont know"
    ]

    query_lower = query.lower()
    has_vague_language = any(indicator in query_lower for indicator in vague_indicators)
    is_good = word_count <= 20 and not has_vague_language and not likely_shell_mangled

    return is_good, word_count, has_vague_language, likely_shell_mangled


def is_expensive_command(command: str) -> tuple[bool, str | None]:
    """Check if a command might be slow or produce excessive output."""
    expensive_patterns = [
        ("find ~", "searching your entire home directory"),
        ("find /", "searching your entire computer"),
        ("grep -r ~", "searching all files in your home directory"),
        ("grep -r /", "searching all files on your computer"),
        ("du -a ~", "calculating size of everything in your home directory"),
        ("du -a /", "calculating size of everything on your computer"),
        ("find . -name", "searching this folder and all nested folders"),
        ("find . -type", "searching this folder and all nested folders"),
    ]

    for pattern, reason in expensive_patterns:
        if pattern in command:
            return True, reason

    return False, None


def clean_command_output(response: str) -> str:
    """
    Clean the model output to extract only the command.
    Handles ChatML tags, markdown, placeholders, and multi-line responses.
    """
    # Remove ChatML end tags
    response = response.replace("<|im_end|>", "")
    response = response.replace("<|endoftext|>", "")
    response = response.replace("<|end_of_text|>", "")

    # Remove markdown code blocks
    response = response.replace("```bash", "").replace("```sh", "").replace("```", "")

    # Remove placeholder brackets
    response = re.sub(r"\[\[\[(.*?)\]\]\]", r"\1", response)
    response = re.sub(r"\[\[(.*?)\]\]", r"\1", response)
    response = re.sub(r"\[-(.*?)-\]", r"\1", response)

    # Normalize whitespace
    response = " ".join(response.split())

    lines = [line.strip() for line in response.split("\n") if line.strip()]

    if len(lines) > 1:
        has_continuation = any(line.endswith("\\") for line in lines[:-1])
        has_heredoc = any(re.search(r"<<\s*\w+", line) for line in lines)
        has_pipe_continuation = any(line.endswith("|") for line in lines[:-1])

        second_line_is_explanation = (
            len(lines) > 1 and
            (lines[1][0].isupper() or
             any(lines[1].lower().startswith(word) for word in
                 ["this", "the", "it", "note:", "example:", "usage:"]))
        )

        if second_line_is_explanation:
            response = lines[0]
        elif has_continuation or has_heredoc or has_pipe_continuation:
            response = "\n".join(lines)
        else:
            response = lines[0]
    else:
        response = lines[0] if lines else ""

    response = response.replace("`", "").strip()
    return response


def generate_command(
    llm,
    query: str,
    history: list[tuple[str, str]] | None = None,
    base_temp: float = 0.2,
    temp_increment: int = 0,
    user_context: str | None = None,
    os_name: str | None = None
) -> str:
    """Generate a CLI command using the LLM with retry-aware temperature scaling."""
    if os_name is None:
        os_name = get_os_type()

    system_prompt = (
        f"You are a specialized CLI assistant for {os_name}. "
        f"Provide only the exact command requested. "
        f"Do not include placeholders, brackets, or explanations. "
        f"Output must be a valid, executable command."
    )

    system_part = f"<|im_start|>system\n{system_prompt}<|im_end|>\n"

    history_context = ""
    if history:
        tried_commands = [cmd for cmd, _ in history]
        history_context = "\n\nDo NOT suggest any of these commands (already tried and rejected):\n"
        for cmd in tried_commands[-5:]:
            history_context += f"- {cmd}\n"
        history_context += "\nProvide a DIFFERENT command."

    additional_context = ""
    if user_context:
        additional_context = f"\n\nAdditional context from user: {user_context}"

    prompt = f"{system_part}<|im_start|>user\n{query}{history_context}{additional_context}<|im_end|>\n<|im_start|>assistant\n"

    temp = min(base_temp + (temp_increment * 0.15), 0.8)

    output = llm(
        prompt,
        max_tokens=120,
        stop=["<|im_end|>", "```", "\n\n", "Try:", "Explanation:", "Instead:"],
        echo=False,
        temperature=temp
    )

    cmd = output["choices"][0]["text"].strip()
    return clean_command_output(cmd)


def prompt_yes_no(message: str) -> bool:
    """Prompt user for yes/no input. Re-prompts on ambiguous input."""
    while True:
        choice = input(message).lower().strip()
        if choice in AFFIRMATIVE:
            return True
        elif choice in NEGATIVE:
            return False
        else:
            print("   Please enter y or n.")


def prompt_for_context(user_context: str | None) -> tuple[str | None, bool]:
    """Prompt user for additional context. Returns (new_context, was_provided)."""
    print("\n💡 Having trouble finding the right command?")
    context_input = input("💬 Add context to help? (or 'n' to skip): ").strip()
    if context_input and context_input.lower() not in NEGATIVE:
        return context_input, True
    return user_context, False
