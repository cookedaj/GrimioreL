import sys

if sys.argv[1:2] in (["update"], ["--update"]):     # `grimoire update` works without a display
    from grimoire.update import cli
    sys.exit(cli(sys.argv[2:]))

from grimoire.app import main

main()
