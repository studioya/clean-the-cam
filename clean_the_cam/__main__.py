import sys


def run():
    """`--cli` anywhere -> batch mode with no window; otherwise the window,
    with any file paths on the command line preselected."""
    args = sys.argv[1:]
    if '--cli' in args:
        from . import cli
        sys.exit(cli.main([a for a in args if a != '--cli']))
    from . import gui
    gui.main(args or None)


if __name__ == '__main__':
    run()
