import logging


class CustomAdapter(logging.LoggerAdapter):
    """
    This adapter prefix the log messages by a given 'prefix' key
    """

    def process(self, msg, kwargs):
        return '[%s] %s' % (self.extra['prefix'], msg), kwargs
