#!/bin/bash

# Navigate to the project directory
cd "$(dirname "$0")"

# Activate virtual environment
source myenv/bin/activate

# Run the management command
python3 manage.py refresh_transactions

# Deactivate virtual environment
deactivate 