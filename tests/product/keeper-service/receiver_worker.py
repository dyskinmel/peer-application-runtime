"""Separate recipient process. The job contains public synthetic test keys only."""
from pathlib import Path
import hashlib,json,signal,sys
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT/'tools'))
import keeper_service_host # Path bootstrap only; does not run a service or import tests.
from par_crypto.provider import SodiumProvider
from par_keeper.contract import pin_from
from par_recovery import Inbox
from par_keeper_service import Client,RemoteProvider
from par_wire.codec import decode

def main():
    job=json.loads(Path(sys.argv[1]).read_text());p=SodiumProvider(json.loads((ROOT/'policy/crypto-provider.json').read_text()),allow_legacy_experiment=True)
    b=lambda k:bytes.fromhex(job[k]);pin=pin_from(decode(b('pin')))
    client=Client(Path(job['socket']),p,b('keeper'),b('subject_seed'),b('capability'))
    remote=RemoteProvider(client,b('lease'),b('index'),pin);fetched=[]
    def fetch(oid):fetched.append(oid.hex());return remote.fetch(oid)
    class Counted:
        @staticmethod
        def fetch(oid):return fetch(oid)
    with Inbox(Path(job['inbox']),b('index'),pin) as rx:
        before=len(rx.missing())
        if len(sys.argv)>2 and sys.argv[2]=='partial':rx.pull(Counted(),limit=1)
        else:
            while rx.missing():rx.pull(Counted(),limit=8)
            view=rx.finalize(Path(job['destination']),p,b('recipient_secret'))
            view.export_file(pin.roots[0],Path(job['output']))
            print(json.dumps({'state':'RECOVERED','status':view.status(),'fetched':fetched,'before_missing':before,'sha256':hashlib.sha256(Path(job['output']).read_bytes()).hexdigest()}),flush=True);return
    print(json.dumps({'state':'PARTIAL_PERSISTED','fetched':fetched,'before_missing':before}),flush=True)
    signal.pause() # Parent owns this process and SIGKILLs only after reading the marker.
if __name__=='__main__':main()
