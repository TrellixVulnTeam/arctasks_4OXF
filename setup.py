import sys
from distutils.core import setup

install_requires = [
    'invoke>=0.11.1',
]

if sys.version_info[:2] < (3, 4):
    install_requires.append('enum34')

setup(
    name='psu.oit.arc.tasks',
    version='0.0.0.dev0',
    author='Wyatt Baldwin',
    author_email='wyatt.baldwin@pdx.edu',
    description='Tasks',
    license='MIT',
    packages=['arctasks'],
    url='https://github.com/PSU-OIT-ARC/arctasks',
    install_requires=install_requires,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Topic :: Software Development :: Build Tools',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
    ],
)
