from distutils.core import setup

setup(
    name='psu.oit.arc.tasks',
    version='0.0.0.dev0',
    author='Wyatt Baldwin',
    author_email='wyatt.baldwin@pdx.edu',
    description='Tasks',
    license='MIT',
    packages=['arctasks'],
    url='https://github.com/PSU-OIT-ARC/arctasks',
    install_requires=[
        'invoke',
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Topic :: Software Development :: Build Tools',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
    ],
)
