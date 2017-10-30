from requests_aws4auth import AWS4Auth
import boto3


def _get_ssm_parameter(parameter_name, region_name=None):
    client = boto3.session.Session(region_name=region_name).client('ssm')
    return client.get_parameters(Names=[parameter_name],
                                 WithDecryption=True)['Parameters'][0]['Value']


def set_secret_key(settings):
    """
    Fetches application secret key from SSM.
    """
    if not settings['DEBUG']:
        parameter_name = '/{}/DBPassword'.format(settings['SSM_KEY'])
        settings['SECRET_KEY'] = _get_ssm_parameter(parameter_name,
                                                    region_name=settings['AWS_REGION'])


def set_database_parameters(settings):
    """
    Fetches RDS authentication parameters from SSM.
    """
    if 'rds.amazonaws.com' in settings['DATABASES']['default']['HOST']:
        parameter_name = '/{}/DBPassword'.format(settings['SSM_KEY'])
        settings['DATABASES']['default']['PASSWORD'] = \
            _get_ssm_parameter(parameter_name,
                               region_name=settings['AWS_REGION'])


def set_elasticsearch_kwargs(settings):
    """
    Intelligently sets HTTP authentication when using AWS Elasticsearch service.
    """
    import elasticsearch

    def generate_kwargs(configuration_key, host_key):
        try:
            kwargs = settings[configuration_key]['default']['KWARGS']
        except KeyError:
            kwargs = {}

        if 'es.amazonaws.com' in settings[configuration_key]['default'][host_key]:
            session = boto3.session.Session(region_name=settings['AWS_REGION'])
            credentials = session.get_credentials()
            awsauth = AWS4Auth(
                credentials.access_key,
                credentials.secret_key,
                session.region_name,
                'es',
                session_token=credentials.token
            )

            kwargs.update(
                http_auth=awsauth,
                connection_class=elasticsearch.RequestsHttpConnection,
            )

            return kwargs

    settings['HAYSTACK_CONNECTIONS']['default']['KWARGS'] = \
        generate_kwargs('HAYSTACK_CONNECTIONS', 'URL')
    settings['ELASTICSEARCH_CONNECTIONS']['default']['KWARGS'] = \
        generate_kwargs('ELASTICSEARCH_CONNECTIONS', 'HOSTS')
