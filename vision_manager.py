from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--maintenance":
        from vision_mcp.cli import main as cli_main

        return cli_main(sys.argv[2:])

    from vision_mcp.web_manager import main as manager_main

    manager_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
