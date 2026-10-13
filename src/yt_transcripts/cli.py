"""`ytt` command line. Works in any terminal and in agent mode of any AI app (no MCP needed)."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _print(obj: Any) -> None:
    if isinstance(obj, dict) and set(obj) >= {"text"} and len(obj.get("text", "")) > 0 and not obj.get("error"):
        meta = {k: v for k, v in obj.items() if k != "text"}
        print(json.dumps(meta, ensure_ascii=False))
        print(obj["text"])
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ytt", description="Resumable, rate-limited YouTube transcripts.")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="transcript of one video (cached after first fetch)")
    g.add_argument("video")
    g.add_argument("--start"), g.add_argument("--end")
    g.add_argument("--offset", type=int, default=0)
    g.add_argument("--max-chars", type=int)
    g.add_argument("--search", default="")
    g.add_argument("--ts", type=int, help="timestamp every N seconds (0 = none)")
    g.add_argument("--refresh", action="store_true")

    o = sub.add_parser("outline", help="chapters/sections with sizes")
    o.add_argument("video")

    j = sub.add_parser("job", help="playlist/channel jobs (run in background)")
    js = j.add_subparsers(dest="jcmd", required=True)
    s = js.add_parser("start")
    s.add_argument("source", help="playlist/channel URL, video URL, or comma-separated ids")
    s.add_argument("--title", default="")
    s.add_argument("--foreground", action="store_true", help="run in this terminal instead of background")
    st = js.add_parser("status")
    st.add_argument("job_id", nargs="?")
    st.add_argument("-v", "--verbose", action="store_true")
    for name in ("pause", "cancel", "resume", "export"):
        x = js.add_parser(name)
        x.add_argument("job_id")

    n = sub.add_parser("notes", help="AI note-taking progress per job")
    ns = n.add_subparsers(dest="ncmd", required=True)
    nx = ns.add_parser("next")
    nx.add_argument("job_id")
    nx.add_argument("-n", type=int, default=1)
    nd = ns.add_parser("done")
    nd.add_argument("job_id")
    nd.add_argument("video_ids", nargs="+")
    nd.add_argument("--ref", default="")

    im = sub.add_parser("import", help="import a caption file (json3/vtt/srt/xml) captured elsewhere")
    im.add_argument("video"), im.add_argument("file")
    im.add_argument("--title", default="")

    sub.add_parser("recover", help="restart interrupted/due jobs (safe to schedule every 30 min)")
    d = sub.add_parser("doctor", help="check installation; --live VIDEO runs a real fetch")
    d.add_argument("--live", metavar="VIDEO")
    sub.add_parser("update", help="update the YouTube layer (yt-dlp, PO-token plugin, fallback lib)")
    sub.add_parser("config", help="show effective settings")
    sub.add_parser("throttle-reset", help="clear backoff state (use only if you know the block is over)")
    ic = sub.add_parser("install-clients", help="register the MCP server in AI apps (backs up configs)")
    ic.add_argument("targets", nargs="*", default=["claude", "cursor", "codex", "vscode", "claude-code"],
                    help="any of: claude cursor codex vscode claude-code (default: all)")
    sv = sub.add_parser("serve", help="run the MCP server (stdio by default)")
    sv.add_argument("--http", type=int, metavar="PORT", help="serve streamable HTTP on 127.0.0.1:PORT instead")

    # internal
    f = sub.add_parser("_fetch")
    f.add_argument("video_id")
    w = sub.add_parser("_work")
    w.add_argument("job_id")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "serve":
        from .server import run
        run(http_port=args.http)
        return 0
    if args.cmd == "install-clients":
        from .clients import install
        for line in install(args.targets):
            print(line)
        return 0

    from .service import Service
    svc = Service()

    if args.cmd == "_fetch":
        print(json.dumps(svc.fetch_child(args.video_id)))
        return 0
    if args.cmd == "_work":
        print(f"worker result: {svc.run_job(args.job_id)}", flush=True)
        return 0
    if args.cmd == "get":
        _print(svc.get_transcript(args.video, args.start, args.end, args.offset, args.max_chars, args.search,
                                  args.ts, args.refresh, max_wait=600))
    elif args.cmd == "outline":
        _print(svc.get_outline(args.video, max_wait=600))
    elif args.cmd == "job":
        if args.jcmd == "start":
            r = svc.create_job(args.source, args.title)
            if "job_id" in r:
                if args.foreground:
                    svc.store.update_job(r["job_id"], status="pending")
                    r["result"] = svc.run_job(r["job_id"])
                else:
                    r.update(svc.start_job(r["job_id"]))
            _print(r)
        elif args.jcmd == "status":
            _print(svc.job_status(args.job_id, args.verbose))
        elif args.jcmd == "pause":
            _print(svc.pause_job(args.job_id))
        elif args.jcmd == "cancel":
            _print(svc.cancel_job(args.job_id))
        elif args.jcmd == "resume":
            _print(svc.start_job(args.job_id))
        elif args.jcmd == "export":
            _print(svc.export_job(args.job_id))
    elif args.cmd == "notes":
        if args.ncmd == "next":
            _print(svc.next_for_notes(args.job_id, args.n))
        else:
            _print(svc.mark_notes(args.job_id, args.video_ids, args.ref))
    elif args.cmd == "import":
        _print(svc.import_captions(args.video, args.file, title=args.title))
    elif args.cmd == "recover":
        _print({"started": svc.recover()})
    elif args.cmd == "doctor":
        _print(svc.doctor(args.live))
    elif args.cmd == "update":
        _print(svc.update())
    elif args.cmd == "config":
        _print(svc.s.public_dict())
    elif args.cmd == "throttle-reset":
        svc.throttle.reset()
        _print(svc.throttle.status())
    return 0


if __name__ == "__main__":
    sys.exit(main())
