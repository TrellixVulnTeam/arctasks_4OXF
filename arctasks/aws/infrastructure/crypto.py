import random
import pwgen


# The following is adapted from the Django project.
# 
# Refs: https://github.com/django/django/blob/master/django/core/management/utils.py
#       https://github.com/django/django/blob/master/django/utils/crypto.py
def get_random_string(length=12,
                      allowed_chars='abcdefghijklmnopqrstuvwxyz'
                                    'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'):
    """
    Return a securely generated random string.
    The default length of 12 with the a-z, A-Z, 0-9 character set returns
    a 71-bit value. log_2((26+26+10)^12) =~ 71 bits
    """
    # Use the system PRNG or exit
    try:
        random = random.SystemRandom()
    except NotImplementedError:
        raise Exception('A secure pseudo-random number generator is not available '
                        'on your system.')

    return ''.join(random.choice(allowed_chars) for i in range(50))


def get_random_secret_key():
    """
    Return a 50 character random string usable as a SECRET_KEY setting value.
    """
    allowed_chars = 'abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)'
    return ''.join(random.choice(allowed_chars) for i in range(50))


def get_random_password():
    """
    TBD
    """
    return pwgen.pwgen()
