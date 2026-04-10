import argparse
from pathlib import Path

from uillc.llcMgm import LLCManagementApp
from uillc.llcSession import build_default_session


def llcMgmtCmd(
    eSession=None,
    base_dir=".",
    host="127.0.0.1",
    port=5000,
    debug=False,
    notebook=False
):
    session = eSession or build_default_session(base_dir)
    app = LLCManagementApp(eSession=session)
    return app.run(host=host, port=port, debug=debug, notebook=notebook)


def main():
    parser = argparse.ArgumentParser(description="Start LLC Management Flask app")
    parser.add_argument("--base-dir", default=str(Path(".").resolve()))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--notebook", action="store_true")
    args = parser.parse_args()

    llcMgmtCmd(
        eSession=None,
        base_dir=args.base_dir,
        host=args.host,
        port=args.port,
        debug=args.debug,
        notebook=args.notebook
    )


if __name__ == "__main__":
    main()
