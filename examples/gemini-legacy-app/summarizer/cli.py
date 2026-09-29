"""Command line entry point: `python -m summarizer.cli <file>`."""

import argparse
import sys

from .conversation import FollowUp
from .summarize import summarize_file


def build_parser():
    parser = argparse.ArgumentParser(
        prog="summarize",
        description="Summarise a text file, then optionally ask one follow-up question.",
    )
    parser.add_argument("path", help="path to a UTF-8 text file")
    parser.add_argument(
        "-n",
        "--sentences",
        type=int,
        default=3,
        help="maximum number of sentences in the summary (default: 3)",
    )
    parser.add_argument(
        "--ask",
        metavar="QUESTION",
        default=None,
        help="ask one follow-up question about the summary",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        summary = summarize_file(args.path, sentences=args.sentences)
    except OSError as exc:
        print("cannot read {}: {}".format(args.path, exc), file=sys.stderr)
        return 2
    print(summary)
    if args.ask:
        print()
        print(FollowUp(summary).ask(args.ask))
    return 0


if __name__ == "__main__":
    sys.exit(main())
