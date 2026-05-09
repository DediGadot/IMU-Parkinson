"""Probe Synapse access for WearGait-PD raw 22-ch download (slot C activation).

Usage on remote:
  SYNAPSE_AUTH_TOKEN=<token> ~/pd-imu/.venv/bin/python probe_synapse.py
"""
from __future__ import annotations

import os
import sys

import synapseclient


def main() -> int:
    token = os.environ.get("SYNAPSE_AUTH_TOKEN", "").strip()
    if not token:
        print("ERROR: SYNAPSE_AUTH_TOKEN env var not set.", file=sys.stderr)
        return 2
    print(f"token_len={len(token)}", flush=True)
    syn = synapseclient.Synapse()
    syn.login(authToken=token)
    me = syn.getUserProfile()
    print(f"logged_in_as={me['userName']!r} ownerId={me['ownerId']}", flush=True)
    for entid in ("syn61370558", "syn55105530"):
        try:
            ent = syn.get(entid, downloadFile=False)
            print(f"{entid} type={type(ent).__name__} name={ent.name!r}", flush=True)
            children = list(syn.getChildren(entid, includeTypes=["folder", "file"]))
            print(f"  children_count={len(children)}", flush=True)
            for c in children[:10]:
                print(f"    {c.get('id')} {c.get('type')} {c.get('name')}", flush=True)
        except Exception as exc:
            print(f"{entid} ERROR {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
