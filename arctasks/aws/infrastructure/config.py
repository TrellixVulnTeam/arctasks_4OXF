from . import crypto


RESOURCE_SECRETS = {
    'app': [('SecretKey', crypto.get_random_secret_key)],
    'rds': [('DBPassword', crypto.get_random_password)]
}

RESOURCE_PARAMETERS = {
    'commands': {
        'Database': {
            'RDSEndpoint': 'db.host'
        },
        'SearchIndex': {
            'EsEndpoint': 'index.url'
        }
    },
    'app': {
        'Database': {
            'DATABASES.default.HOST': 'db.host',
            'DATABASES.default.NAME': 'db.name',
            'DATABASES.default.USER': 'db.user',
            'DATABASES.default.PASSWORD': None,
        },
        'SearchIndex': {
            'HAYSTACK_CONNECTIONS.default.URL': 'index.url',
            'HAYSTACK_CONNECTIONS.default.INDEX_NAME': 'index.name',
            'ELASTICSEARCH_CONNECTIONS.default.HOSTS': 'index.url',
            'ELASTICSEARCH_CONNECTIONS.default.INDEX_NAME': 'index.name'
        }
    }
}
