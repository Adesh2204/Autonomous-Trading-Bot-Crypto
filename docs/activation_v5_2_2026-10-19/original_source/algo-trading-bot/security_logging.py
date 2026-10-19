import logging

class BrokerSecretFilter(logging.Filter):
    def filter(self,record):
        message=record.getMessage()
        if any(marker in message.lower() for marker in ('loginbypassword','password','totp','authorization','x-privatekey','jwttoken','refreshtoken')):
            record.msg='Broker authentication/request diagnostic redacted'; record.args=()
        return True

def install_broker_secret_filter():
    filter=BrokerSecretFilter()
    logging.getLogger().addFilter(filter)
    for handler in logging.getLogger().handlers:handler.addFilter(filter)
    try:
        from logzero import logger
        logger.addFilter(filter)
    except ImportError:pass
