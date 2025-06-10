#!/bin/bash
# Python notes

# pyenv is used to manage python versions
# venv is used to manage a virtual environment for each project, and is baked into VS Code


### venv for each project workspace

# Use VS Code's python .venv integration to create a .venv dir a the workspace root
# https://code.visualstudio.com/docs/python/environments
# https://docs.python.org/3/library/venv.html

# If VS Code is still showing packages are not available,
# Or if running the script fails to find packages,
# Click on the Python button in the bottom right corner of VS Code,
# Use the Recommended setting, ex. [workspace-root]/.venv/bin/python

# Activate the virtual environment in the terminal
# Either manually, from the workspace root
source .venv/bin/activate
# Or every time, with the VS Code setting
# python.terminal.activateEnvironment


### Use pip to install packages, after activating the venv

# Update pip and packages
pip install --upgrade pip pipreqs

# Create requirements.txt file
pipreqs . --force

# Install requirements from requirements.txt
pip install -r requirements.txt --upgrade

# List installed packages
pip list


### System-wide python

# Verify the path to python
which python
# [2025-05-30 18:06:00] ~ % which python
# ~/.pyenv/shims/python

# Verify python version
python --version
# [2025-05-30 18:06:02] ~ % python --version
# Python 3.13.2

# Update brew catalogues
brew update

# Upgrade pyenv to latest
brew upgrade pyenv

# Upgrade all brew packages to latest
# brew upgrade

# Update system-wide python to latest v3
latest="$(pyenv latest -k 3)"; pyenv install "$latest" && pyenv global "$latest"

# Verify the path to python
which python
# [2025-05-30 18:16:38] ~ % which python
# ~/.pyenv/shims/python

# Verify python version
python --version
# [2025-05-30 18:16:46] ~ % python --version
# Python 3.13.3
