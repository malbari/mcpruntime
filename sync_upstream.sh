#!/bin/bash

# Configuration
UPSTREAM_URL="https://github.com/TJKlein/mcpruntime.git"
UPSTREAM_NAME="upstream"
MAIN_BRANCH="master"

echo "Checking for upstream remote..."

# Add upstream if it doesn't exist
if ! git remote | grep -q "^$UPSTREAM_NAME$"; then
    echo "Adding upstream remote: $UPSTREAM_URL"
    git remote add $UPSTREAM_NAME $UPSTREAM_URL
else
    echo "Upstream remote already exists."
fi

echo "Fetching from upstream..."
git fetch $UPSTREAM_NAME

echo "Current branch is: $(git branch --show-current)"

echo "Merging $UPSTREAM_NAME/$MAIN_BRANCH into current branch..."
if git merge $UPSTREAM_NAME/$MAIN_BRANCH; then
    echo "Successfully merged upstream changes."
    echo "You can now push to your origin with: git push origin $(git branch --show-current)"
else
    echo "Conflict detected during merge. Please resolve conflicts and commit."
fi
