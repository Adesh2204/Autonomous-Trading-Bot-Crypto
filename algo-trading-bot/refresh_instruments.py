"""Read-only broker-master/eligibility refresh. Never places orders."""
import json
from pathlib import Path
import requests
from instrument_registry import InstrumentRegistry
from execution_safety import SafetyError

MASTER_URL='https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
INTRADAY_URL='https://apiconnect.angelone.in/rest/secure/angelbroking/marketData/v1/nseIntraday'

def refresh_registry(broker,path,now,get=requests.get):
    if broker is None:raise SafetyError('BROKER_DATA_UNAVAILABLE')
    master=get(MASTER_URL,timeout=20); master.raise_for_status(); records=master.json()
    headers=broker.requestHeaders()
    token=broker.access_token
    headers['Authorization']=token if str(token).startswith('Bearer ') else 'Bearer '+str(token)
    headers['X-PrivateKey']=broker.api_key
    response=get(INTRADAY_URL,headers=headers,timeout=20); response.raise_for_status(); allowed=response.json()
    if not isinstance(records,list) or allowed.get('status') is not True or not isinstance(allowed.get('data'),list):
        raise SafetyError('INVALID_INSTRUMENT_SOURCE')
    symbols=[r['SymbolName'] for r in allowed['data'] if r.get('exchange')=='NSE']
    registry=InstrumentRegistry(records,now,symbols)
    if not registry.by_symbol:raise SafetyError('EMPTY_ELIGIBLE_UNIVERSE')
    envelope={'source_timestamp':now.isoformat(),'records':records,'intraday_symbols':symbols,
              'restricted_symbols':[],'sources':[MASTER_URL,INTRADAY_URL],
              'restriction_status':'INTRADAY_ELIGIBILITY_VERIFIED; OTHER_SURVEILLANCE_RESTRICTIONS_REQUIRE_QUOTE/BROKER_CHECK'}
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp'); temp.write_text(json.dumps(envelope)); temp.replace(path)
    return registry
