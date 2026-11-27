"""Argument parsing for the laminprofiler executable."""

from __future__ import annotations

import click

_PROFILE = "profile"


def normalize_args(args: list[str]) -> list[str]:
    """Send a path invocation through the profiling command.

    `laminprofiler run` stays a subcommand. Every other invocation profiles
    and records.
    """
    if not args or args[0] in {"-h", "--help", "run"}:
        return list(args)
    return [_PROFILE, *args]


class LaminProfilerGroup(click.Group):
    """Expose profiling as the default command and keep `run` beside it."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        return super().parse_args(ctx, normalize_args(list(args)))

    def get_help(self, ctx: click.Context) -> str:
        command = self.get_command(ctx, _PROFILE)
        if command is None:
            return super().get_help(ctx)
        sub_ctx = click.Context(command, info_name=ctx.info_name, parent=ctx)
        return command.get_help(sub_ctx)
