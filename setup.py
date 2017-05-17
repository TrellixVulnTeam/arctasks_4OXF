import sys
from distutils.core import setup

install_requires = [
    'boto3>=1.4.4',
    'runcommands>=1.0a20',
    'setuptools>=35.0.2',
]

if sys.version_info[:2] < (3, 4):
    install_requires.append('enum34')

setup(
    name='psu.oit.arc.tasks',
    version='1.0.0.dev0',
    author='Wyatt Baldwin',
    author_email='wbaldwin@pdx.edu',
    description='Commands for WDT (formerly ARC) projects',
    license='MIT',
    url='https://github.com/PSU-OIT-ARC/arctasks',
    install_requires=install_requires,
    packages=['arctasks', 'arctasks.aws'],
    package_data={
        'arctasks': [
            'commands.cfg',
            'rsync.excludes',
            'templates/*.template',
        ],
        'arctasks.aws': [
            '*.conf',
            '*.ini',
            'commands.cfg',
            'templates/*.template',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Topic :: Software Development :: Build Tools',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
)
