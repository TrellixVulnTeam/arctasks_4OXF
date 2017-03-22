import sys
from distutils.core import setup

install_requires = [
    'boto3>=1.4.4',
    'runcommands>=1.0a7',
    'setuptools>=34.3.2',
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
    packages=['arctasks'],
    package_data={
        'arctasks': ['rsync.excludes', 'commands.cfg', 'templates/*'],
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
