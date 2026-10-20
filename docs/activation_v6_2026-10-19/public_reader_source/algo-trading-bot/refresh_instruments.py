"""Read-only broker-master/eligibility refresh. Never places orders."""
import requests
from execution_safety import SafetyError
from market_universe import build_market_universe, normalize_symbol
from discovery_data import atomic_json

MASTER_URL='https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
INTRADAY_URL='https://apiconnect.angelone.in/rest/secure/angelbroking/marketData/v1/nseIntraday'

def refresh_registry(broker,path,now,get=requests.get):
    if broker is None:raise SafetyError('BROKER_DATA_UNAVAILABLE')
    master=get(MASTER_URL,timeout=20); master.raise_for_status(); records=master.json()
    headers=dict(broker.requestHeaders())
    token=broker.access_token
    headers['Authorization']=token if str(token).startswith('Bearer ') else 'Bearer '+str(token)
    headers['X-PrivateKey']=broker.api_key
    response=get(INTRADAY_URL,headers=headers,timeout=20); response.raise_for_status(); allowed=response.json()
    if not isinstance(records,list) or allowed.get('status') is not True or not isinstance(allowed.get('data'),list):
        raise SafetyError('INVALID_INSTRUMENT_SOURCE')
    symbols=[]
    for row in allowed['data']:
        if (not isinstance(row,dict) or not isinstance(row.get('SymbolName'),str) or
                not row['SymbolName'].strip() or not any(k in row for k in ('Exchange','exchange'))):
            raise SafetyError('SCHEMA_VALIDATION_FAILED: intraday eligibility')
        if ('Exchange' in row and 'exchange' in row and
                str(row['Exchange']).strip().upper()!=str(row['exchange']).strip().upper()):
            raise SafetyError('SCHEMA_VALIDATION_FAILED: conflicting eligibility exchange')
        exchange=str(row.get('Exchange',row.get('exchange'))).strip().upper()
        if exchange=='NSE':symbols.append(normalize_symbol(row['SymbolName']))
    envelope={'source_timestamp':now.isoformat(),'records':records,'intraday_symbols':symbols,
              'restricted_symbols':[],'sources':[MASTER_URL,INTRADAY_URL],
              'restriction_status':'INTRADAY_ELIGIBILITY_VERIFIED; OTHER_SURVEILLANCE_RESTRICTIONS_REQUIRE_QUOTE/BROKER_CHECK'}
    registry=build_market_universe(envelope,now).registry
    if not registry.by_symbol:raise SafetyError('EMPTY_ELIGIBLE_UNIVERSE')
    atomic_json(path,envelope)
    return registry
