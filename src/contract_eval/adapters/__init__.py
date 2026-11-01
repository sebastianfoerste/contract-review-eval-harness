"""Adapter factory."""

import argparse
from dataclasses import dataclass

from contract_eval.adapters.base import Adapter
from contract_eval.adapters.stub import StubAdapter

ADAPTER_NAMES = ("stub", "anthropic", "openai-compatible", "command")


@dataclass(frozen=True)
class AdapterChoice:
    """The adapter a caller asked for by name, and the settings only some adapters use.

    `get_adapter(live)` predates the other providers and stays callable that way:
    without a choice, `live` still picks between the stub and Anthropic.
    """

    name: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    command: str | None = None


def adapter_name(live: bool, choice: AdapterChoice | None = None) -> str:
    if choice is not None and choice.name is not None:
        if choice.name not in ADAPTER_NAMES:
            raise ValueError(f"unknown adapter {choice.name!r}; choose one of {', '.join(ADAPTER_NAMES)}")
        return choice.name
    return "anthropic" if live else "stub"


def get_adapter(live: bool, model: str | None = None, choice: AdapterChoice | None = None) -> Adapter:
    name = adapter_name(live, choice)
    choice = choice or AdapterChoice()
    if name == "anthropic":
        from contract_eval.adapters.live import LiveAdapter  # lazy: no SDK/key needed offline

        return LiveAdapter(model=model)
    if name == "openai-compatible":
        from contract_eval.adapters.openai_compat import OpenAICompatibleAdapter

        return OpenAICompatibleAdapter(
            model=model, base_url=choice.base_url, api_key_env=choice.api_key_env
        )
    if name == "command":
        from contract_eval.adapters.command import CommandAdapter

        return CommandAdapter(choice.command)
    return StubAdapter()


def adapter_identifier(live: bool, model: str | None = None, choice: AdapterChoice | None = None) -> str:
    """Name the adapter that produced a result, for the run history and scorecards."""
    name = adapter_name(live, choice)
    if name == "stub":
        return "stub"
    if name == "openai-compatible":
        from contract_eval.adapters.openai_compat import identifier as openai_identifier

        return openai_identifier(model, (choice or AdapterChoice()).base_url)
    if name == "command":
        from contract_eval.adapters.command import identifier as command_identifier

        return command_identifier((choice or AdapterChoice()).command)
    from contract_eval.adapters.live import DEFAULT_MODEL

    import os

    return model or os.environ.get("CONTRACT_EVAL_MODEL") or DEFAULT_MODEL


def add_adapter_arguments(parser: argparse.ArgumentParser) -> None:
    """The adapter flags shared by every command that produces a review.

    `--live` is kept as an alias for `--adapter anthropic`: Make targets, CI and the
    docs use it, and a run must not silently change provider when one is renamed.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--adapter",
        default=None,
        choices=ADAPTER_NAMES,
        help="which adapter produces the review (default: stub)",
    )
    group.add_argument("--live", action="store_true", help="alias for --adapter anthropic")
    parser.add_argument(
        "--base-url",
        default=None,
        help="Chat Completions base URL for --adapter openai-compatible "
             "(default: OPENAI_BASE_URL, else https://api.openai.com/v1)",
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        help="name of the environment variable holding the API key for "
             "--adapter openai-compatible (default: OPENAI_API_KEY; may be unset for local servers)",
    )
    parser.add_argument(
        "--command",
        default=None,
        help="program for --adapter command: reads the contract on stdin, prints ReviewOutput JSON",
    )


def adapter_choice(args: argparse.Namespace) -> AdapterChoice:
    return AdapterChoice(
        name=args.adapter,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        command=args.command,
    )
