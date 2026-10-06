import logging

LOG = logging.getLogger("shop")


def audit(message):
    LOG.info(message)


def audit_startup():
    LOG.info("startup " + "ShopApp")
