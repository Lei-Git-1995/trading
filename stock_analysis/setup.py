#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Setup script for stock_analysis package
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_file = Path(__file__).parent / 'README.md'
long_description = readme_file.read_text(encoding='utf-8') if readme_file.exists() else ''

# Read requirements
requirements_file = Path(__file__).parent / 'requirements.txt'
requirements = requirements_file.read_text(encoding='utf-8').strip().split('\n') if requirements_file.exists() else []

setup(
    name='stock_analysis',
    version='2.0.0',
    description='统一的股票技术分析框架',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Stock Analysis Framework',
    packages=find_packages(),
    install_requires=requirements,
    python_requires='>=3.7',
    entry_points={
        'console_scripts': [
            'stock-analysis=stock_analysis.__main__:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Financial and Insurance Industry',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
    ],
)
