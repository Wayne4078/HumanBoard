"""Trusted local-only bootstrap for an empty organization. Never prints credentials."""
import argparse
import json
import os
from pathlib import Path
import re
from storage import provision


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--org',required=True)
    p.add_argument('--org-budget',type=int,default=100000)
    p.add_argument('--credentials',type=Path,required=True,help='New operator-owned JSON file, mode 0600; never commit or share')
    args=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}',args.org): p.error('org must be a simple identifier')
    if not 0 <= args.org_budget <= 100000: p.error('org budget must be 0..100000')
    args.db.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation avoids overwriting operator credentials or following a symlink.
    fd=os.open(args.credentials,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        # Local DB stores bearer hashes; raw tokens go only to this restricted output file.
        tokens=provision(args.db,args.org,args.org_budget,
                         {args.org+'-'+role:role for role in ('admin','ai_customer','worker','reviewer')})
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump({'organization':args.org,'tokens':tokens},f,indent=2)
            f.write('\n')
        os.chmod(args.db,0o600)
    except Exception:
        try: os.close(fd)
        except OSError: pass
        args.credentials.unlink(missing_ok=True)
        raise
    print('V1.1 database initialized. Separate role credentials saved to the protected local file. No tasks posted.')


if __name__=='__main__': main()
