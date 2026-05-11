#!/bin/bash

echo "==================================="
echo "Starting Jekyll Blog on port 4001"
echo "==================================="

# Check if bundle is installed
if ! command -v bundle &> /dev/null; then
    echo "Error: bundler is not installed."
    echo "Please install it with: gem install bundler"
    exit 1
fi

# Install dependencies if needed
echo "Checking dependencies..."
bundle install

# Start Jekyll server on port 4001
echo "Starting server at http://localhost:4001"
bundle exec jekyll serve --port 4001 --future
